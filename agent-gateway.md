# Agent Gateway

## Overview
The Agent Gateway is a FastAPI service that provides a secure interface between frontend applications and the agent event system. It handles Server-Sent Events (SSE) streaming, message validation, and reliable delivery of agent events to clients. It is a core component of the event-driven, micro-agent architecture. outlined here (link coming soon).

## Core Features
- SSE streaming of agent events
- Final payload retrieval endpoint
- Message validation and error handling
- Dead letter handling for corrupt messages
- Health check endpoint

## Data Models

### AgentEvent Schema
```python
class AgentEvent:
    task_id: str      # Unique identifier for the task
    agent_id: str     # Identifier of the agent
    agent_name: str   # Human-readable agent name
    event_index: int  # Sequence number of the event
    timestamp: datetime
    event_type: str   # Type of event (e.g., "chunk_stream", "final_payload")
    payload: dict     # Event-specific data payload
```

## API Endpoints

### Stream Events
```
GET /stream/{task_id}
```
- Creates an SSE connection for real-time event streaming
- Streams all events for a given task
- Automatically closes when "final_payload" is received
- Handles connection cleanup on client disconnect

### Get Final Payload
```
GET /final/{task_id}
```
- Waits for and returns only the final payload
- Useful for clients that don't need streaming updates
- Returns 404 if final payload not found
- Returns 500 on processing errors

### Health Check
```
GET /health
```
- Verifies Service Bus connectivity
- Returns status: "healthy" on success

## Error Handling
1. Message Processing
   - Validates message format using Pydantic
   - Dead-letters corrupt or invalid messages
   - Logs detailed error information

2. Connection Management
   - Automatic cleanup of stale connections
   - Graceful handling of client disconnects
   - Service Bus session management

## Configuration
Required environment variables:
```
AZURE_SERVICE_BUS_CONNECTION_STRING
AZURE_SERVICE_BUS_TOPIC_NAME
AZURE_SERVICE_BUS_SUBSCRIPTION_NAME
```

## Client Integration
Headers required for SSE connection:
```http
Cache-Control: no-cache
Connection: keep-alive
Accept: text/event-stream
```

Example client connection:
```javascript
const eventSource = new EventSource(`/stream/${taskId}`);

eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    // Handle event data
    if (data.event_type === 'final_payload') {
        eventSource.close();
    }
};
```

## Deployment Considerations
1. Scaling
   - Stateless design allows horizontal scaling
   - Service Bus sessions ensure ordered delivery
   - Connection tracking per task ID

2. Monitoring
   - Structured logging for all operations
   - Error tracking for dead-lettered messages
   - Health check endpoint for load balancers

3. Security
   - CORS configuration required
   - No direct Service Bus exposure
   - Input validation on all endpoints