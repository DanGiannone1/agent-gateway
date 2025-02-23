from azure.servicebus import ServiceBusClient, ServiceBusReceiveMode, ServiceBusSubQueue, NEXT_AVAILABLE_SESSION
import os

CONN_STR = os.getenv("AZURE_SERVICE_BUS_CONNECTION_STRING")
TOPIC_NAME = os.getenv("AZURE_SERVICE_BUS_TOPIC_NAME")
SUBSCRIPTION_NAME = os.getenv("AZURE_SERVICE_BUS_SUBSCRIPTION_NAME")

def clear_session_messages(sub_queue=None):
    with ServiceBusClient.from_connection_string(CONN_STR) as client:
        while True:
            try:
                # Use the session-enabled receiver by specifying the next available session.
                receiver = client.get_subscription_receiver(
                    topic_name=TOPIC_NAME,
                    subscription_name=SUBSCRIPTION_NAME,
                    session_id=NEXT_AVAILABLE_SESSION,  # Use NEXT_AVAILABLE_SESSION here
                    sub_queue=sub_queue,
                    receive_mode=ServiceBusReceiveMode.RECEIVE_AND_DELETE,
                    max_wait_time=30
                )
                with receiver:
                    print(f"Processing session: {receiver.session.session_id}")
                    total = 0
                    while True:
                        messages = receiver.receive_messages(
                            max_message_count=100,
                            max_wait_time=5
                        )
                        if not messages:
                            break
                        total += len(messages)
                        print(f"Deleted {len(messages)} messages (Session total: {total})")
            except Exception as e:
                if "No unlocked sessions" in str(e):
                    print("No more sessions available")
                    break
                raise

if __name__ == "__main__":
    print("=== Clearing Active Messages ===")
    clear_session_messages()

    print("\n=== Clearing Dead Letters ===")
    clear_session_messages(sub_queue=ServiceBusSubQueue.DEAD_LETTER)
