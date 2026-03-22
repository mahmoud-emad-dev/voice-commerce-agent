import asyncio
from voice_commerce.core.voice.gemini_live_handler import GeminiLiveHandler

async def test_brain():
    # This 'async with' triggers __aenter__ and __aexit__
    async with GeminiLiveHandler() as handler:
        await handler.send_text("Hello! Can you hear me?")
        
        # We 'loop' over the events as they come in
        async for event in handler.receive_events():
            if event["type"] == "text":
                print(f"🤖 AI: {event['text']}", end="", flush=True)
            if event["type"] == "turn_complete":
                print("\n✅ Response finished.")

if __name__ == "__main__":
    asyncio.run(test_brain())