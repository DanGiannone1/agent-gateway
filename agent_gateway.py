import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from azure.servicebus import ServiceBusClient, ServiceBusReceiver

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(title="Agent Gateway")

# Add CORS middleware (adjust origins as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# Environment configuration
config = {
    "connection_string": os.environ["AZURE_SERVICE_BUS_CONNECTION_STRING"],
    "topic_name": os.environ["AZURE_SERVICE_BUS_TOPIC_NAME"],
    "subscription_name": os.environ["AZURE_SERVICE_BUS_SUBSCRIPTION_NAME"]
}

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
            logger.error(f"[ERROR] Error joining message body parts: {e}")
            raise
    else:
        raise ValueError("Unsupported message body type")

# Pydantic model for AgentEvent - matches ServiceBusHandler output exactly
class AgentEvent(BaseModel):
    task_id: str = Field(..., alias="taskId")
    agent_id: str = Field(..., alias="agentId")
    agent_name: str = Field(..., alias="agentName")
    event_type: str = Field(..., alias="eventType")
    event_index: int = Field(..., alias="eventIndex")
    timestamp: datetime
    payload: dict

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda dt: dt.isoformat().replace("+00:00", "Z") if dt.tzinfo else dt.isoformat()
        }

# Active connections tracking (if needed for multicasting)
active_connections: Dict[str, List[asyncio.Queue]] = {}

async def stream_events(task_id: str) -> StreamingResponse:
    """
    Creates an SSE stream for a specific task.
    Uses task_id as the Service Bus session ID.
    """
    async def event_generator():
        # Create a queue for this connection
        queue = asyncio.Queue()
        active_connections.setdefault(task_id, []).append(queue)

        try:
            # Initialize Service Bus client and receiver
            servicebus_client = ServiceBusClient.from_connection_string(config["connection_string"])
            receiver: ServiceBusReceiver = servicebus_client.get_subscription_receiver(
                topic_name=config["topic_name"],
                subscription_name=config["subscription_name"],
                session_id=task_id,
            )

            # Stream messages
            while True:
                try:
                    messages = await asyncio.get_event_loop().run_in_executor(
                        None,
                        receiver.receive_messages,
                        1,   # one message at a time
                        60   # timeout in seconds
                    )

                    if messages:
                        message = messages[0]
                        try:
                            # Decode and validate message
                            body_str = decode_message_body(message.body)
                            event = AgentEvent.model_validate_json(body_str)
                            
                            # Log message receipt
                            message_text = event.payload.get("message", "")
                            logger.info(f"[STREAM] Task {event.task_id} | Event {event.event_index} | {event.event_type} | {message_text}")

                            # Send event to client
                            event_data = json.dumps(event.model_dump(by_alias=True), default=str)
                            yield f"data: {event_data}\n\n"

                            # End stream on final_payload
                            if event.event_type == "final_payload":
                                logger.info(f"[STREAM] Task {task_id} | Received final event, ending stream")
                                break

                        except Exception as processing_error:
                            logger.error(f"[ERROR] Error processing message: {processing_error}")
                            continue
                    else:
                        # No message received
                        await asyncio.sleep(1)

                except Exception as receive_error:
                    logger.error(f"[ERROR] Error receiving messages: {receive_error}")
                    await asyncio.sleep(1)

        except Exception as stream_error:
            logger.error(f"[ERROR] Stream error: {stream_error}")
            yield f"data: {json.dumps({'error': str(stream_error)})}\n\n"

        finally:
            # Cleanup
            try:
                await asyncio.get_event_loop().run_in_executor(None, receiver.close)
                await asyncio.get_event_loop().run_in_executor(None, servicebus_client.close)
            except Exception as cleanup_error:
                logger.error(f"[ERROR] Error during cleanup: {cleanup_error}")

            # Remove connection tracking
            if task_id in active_connections:
                try:
                    active_connections[task_id].remove(queue)
                    if not active_connections[task_id]:
                        del active_connections[task_id]
                except ValueError:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

@app.get("/stream/{task_id}")
async def get_task_events(task_id: str):
    """
    SSE endpoint that streams all events for a given task.
    """
    try:
        return await stream_events(task_id)
    except Exception as e:
        logger.error(f"[ERROR] Error setting up stream: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/final/{task_id}")
async def get_final_payload(task_id: str):
    """
    Returns only the final payload for a task.
    Waits until final_payload event is received.
    """
    try:
        # Initialize Service Bus client and receiver
        servicebus_client = ServiceBusClient.from_connection_string(config["connection_string"])
        receiver: ServiceBusReceiver = servicebus_client.get_subscription_receiver(
            topic_name=config["topic_name"],
            subscription_name=config["subscription_name"],
            session_id=task_id,
        )

        final_payload = None

        # Poll for messages until final_payload received
        while True:
            messages = await asyncio.get_event_loop().run_in_executor(
                None,
                receiver.receive_messages,
                1,   # one message at a time
                60   # timeout in seconds
            )

            if messages:
                message = messages[0]
                try:
                    # Decode and parse message
                    body_str = decode_message_body(message.body)
                    event = AgentEvent.model_validate_json(body_str)
                    
                    # Log message receipt
                    message_text = event.payload.get("message", "")
                    logger.info(f"[FINAL] Task {event.task_id} | Event {event.event_index} | {event.event_type} | {message_text}")

                    # Capture final payload if event_type matches
                    if event.event_type == "final_payload":
                        final_payload = event.payload
                        logger.info(f"[FINAL] Task {task_id} | Received final payload")
                        break

                except Exception as processing_error:
                    logger.error(f"[ERROR] Error processing message: {processing_error}")
                    continue

            else:
                # No message received
                await asyncio.sleep(1)

        # Cleanup
        await asyncio.get_event_loop().run_in_executor(None, receiver.close)
        await asyncio.get_event_loop().run_in_executor(None, servicebus_client.close)

        if final_payload is not None:
            return final_payload
        else:
            raise HTTPException(status_code=404, detail="Final payload not found")

    except Exception as e:
        logger.error(f"[ERROR] Error retrieving final payload: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """
    Health check endpoint to verify Service Bus connectivity.
    """
    try:
        servicebus_client = ServiceBusClient.from_connection_string(config["connection_string"])
        await asyncio.get_event_loop().run_in_executor(None, servicebus_client.close)
        return {"status": "healthy"}
    except Exception as e:
        logger.error(f"[ERROR] Health check failed: {e}")
        raise HTTPException(status_code=500, detail="Health check failed")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)