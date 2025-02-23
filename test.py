import os
import json
import asyncio
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field
from azure.servicebus import ServiceBusClient, ServiceBusReceiver

# Environment configuration
CONNECTION_STRING = os.environ["AZURE_SERVICE_BUS_CONNECTION_STRING"]
QUEUE_NAME = os.environ["AZURE_SERVICE_BUS_QUEUE_NAME"]

# Helper function to decode message bodies
def decode_message_body(body) -> str:
    if isinstance(body, (bytes, bytearray)):
        return body.decode("utf-8")
    elif isinstance(body, str):
        return body
    elif hasattr(body, "__iter__"):
        try:
            return b"".join(list(body)).decode("utf-8")
        except Exception as e:
            print(f"Error joining message body parts: {e}")
            raise
    else:
        raise ValueError("Unsupported message body type")

# Define the event schema using Pydantic
class AgentEvent(BaseModel):
    task_id: str = Field(..., alias="taskId")
    agent_id: str = Field(..., alias="agentId")
    event_index: int = Field(..., alias="eventIndex")
    timestamp: datetime
    is_final: bool = Field(..., alias="isFinal")
    status: Literal["in-progress", "completed", "error"]
    event_type: Literal["partial", "final"] = Field(..., alias="eventType")
    payload: dict

    class Config:
        allow_population_by_field_name = True

async def read_events_for_task(task_id: str, poll_timeout: int = 10, max_no_message_iterations: int = 3):
    print(f"Opening connection to Service Bus for task_id: {task_id}")
    servicebus_client = ServiceBusClient.from_connection_string(CONNECTION_STRING)
    receiver: ServiceBusReceiver = servicebus_client.get_queue_receiver(
        queue_name=QUEUE_NAME,
        session_id=task_id,
    )

    no_message_iterations = 0

    try:
        print("Connection opened. Listening for messages...")
        while True:
            messages = await asyncio.get_event_loop().run_in_executor(
                None,
                receiver.receive_messages,
                1,          # receive one message at a time
                poll_timeout  # timeout in seconds for this poll
            )

            if messages:
                no_message_iterations = 0  # reset counter when a message is received
                for message in messages:
                    try:
                        body_str = decode_message_body(message.body)
                        # Validate the JSON message using Pydantic V2 method
                        event = AgentEvent.model_validate_json(body_str)
                        # Print the full JSON message with datetime converted to string
                        full_json = json.dumps(event.model_dump(by_alias=True), indent=2, default=str)
                        print("Read event:")
                        print(full_json)
                        # Complete the message so it's removed from the queue.
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            receiver.complete_message,
                            message
                        )
                        # Exit if eventType is "final"
                        if event.event_type == "final":
                            print("Final event received. Exiting.")
                            return
                    except Exception as e:
                        print(f"Error processing message: {e}")
                        # Optionally, dead-letter the message if processing fails.
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            receiver.dead_letter_message,
                            message,
                            "Processing error",
                            str(e)
                        )
            else:
                no_message_iterations += 1
                print(f"No messages received in this poll. (Iteration {no_message_iterations}/{max_no_message_iterations})")
                if no_message_iterations >= max_no_message_iterations:
                    print("No more events for this task_id. Exiting.")
                    return

    finally:
        print("Closing connection...")
        await asyncio.get_event_loop().run_in_executor(None, receiver.close)
        await asyncio.get_event_loop().run_in_executor(None, servicebus_client.close)
        print("Connection closed.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python read_events.py <task_id>")
        sys.exit(1)
    task_id = sys.argv[1]
    asyncio.run(read_events_for_task(task_id))
