from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, validator
from datetime import datetime, timedelta
import logging
import json
import traceback
from typing import Optional

from agent.helpers import (
    get_note_from_db,
    save_note,
    search_from_query,
    save_user_info,
    get_latest_user_info,
    get_noaa_station_data,
    get_tide_predictions
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

class UserInfo(BaseModel):
    first_name: str
    fishing_location: str

    class Config:
        json_schema_extra = {
            "example": {
                "first_name": "John",
                "fishing_location": "Cape Cod"
            }
        }

    @validator('first_name')
    def validate_first_name(cls, v):
        if not v.strip():
            raise ValueError('First name cannot be empty')
        return v.strip()

    @validator('fishing_location')
    def validate_fishing_location(cls, v):
        if not v.strip():
            raise ValueError('Fishing location cannot be empty')
        return v.strip()

@app.get("/")
def read_root() -> dict[str, str]:
    return {
        "message": "Welcome! I'm Grandpa Spuds Oakley, your friendly AI fishing guide. Please share your first name and where you'd like to go fishing. I'll help you find the best times to catch striped bass based on moon phases and tides!"
    }

@app.post("/user/info")
async def collect_user_info(request: Request) -> dict[str, str]:
    try:
        # Get raw request body first
        raw_body = await request.body()
        raw_text = raw_body.decode('utf-8')
        logger.info(f"Raw request body: {raw_text}")
        
        # Try to get the message content
        message = None
        
        # Try to parse as JSON first
        try:
            request_body = await request.json()
            logger.info(f"Request body parsed as JSON: {request_body}")
            
            if isinstance(request_body, dict):
                # Try all possible fields where the message might be
                message = (
                    request_body.get('text') or 
                    request_body.get('message') or 
                    request_body.get('input') or 
                    request_body.get('query') or
                    request_body.get('content')
                )
            
            # If we still don't have a message, use the whole body
            if not message:
                message = str(request_body)
                
        except json.JSONDecodeError:
            # If JSON parsing fails, use the raw text
            message = raw_text
            logger.info("Using raw text as message")
        
        logger.info(f"Final message to process: {message}")
        
        if not message:
            raise HTTPException(
                status_code=400,
                detail="I couldn't understand that. Could you try saying something like: 'My name is John and I fish on Long Island Sound'"
            )
        
        # Convert to lowercase for parsing
        message_lower = message.lower()
        
        # Extract name
        first_name = None
        if "name is" in message_lower:
            name_part = message_lower.split("name is")[1]
            # Split on common separators with spaces to avoid partial matches
            for separator in [" and ", ", ", ". ", " i ", " like "]:
                if separator in name_part:
                    name_part = name_part.split(separator)[0]
            first_name = name_part.strip().title()
        
        logger.info(f"Extracted name: {first_name}")
        
        # Extract location
        fishing_location = None
        if "fish" in message_lower:
            for prep in [" on ", " in ", " at "]:
                if prep in message_lower:
                    loc_part = message_lower.split(prep)[1].strip()
                    # Handle location with state/region
                    parts = loc_part.split(",")
                    fishing_location = parts[0].strip().title()
                    if len(parts) > 1:
                        fishing_location += ", " + parts[1].strip().title()
                    break
        
        logger.info(f"Extracted location: {fishing_location}")
        
        # Validate extracted data
        if not first_name or not fishing_location:
            logger.error(f"Failed to extract required fields. Name: {first_name}, Location: {fishing_location}")
            raise HTTPException(
                status_code=400,
                detail="I couldn't catch your name or fishing location. Please try saying something like: 'My name is John and I fish on Long Island Sound'"
            )
        
        # Try to save to database but don't fail if it doesn't work
        try:
            save_result = save_user_info(first_name, fishing_location)
            if not save_result:
                logger.warning("Database save failed but continuing")
        except Exception as e:
            logger.error(f"Database error: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Continue even if database save fails
        
        # Return success response
        response_message = f"Hey {first_name}! Great to meet you. I know {fishing_location} well - that's a fine spot for striped bass fishing. Let me help you figure out the best times to fish there based on the moon and tides."
        logger.info(f"Sending response: {response_message}")
        return {"message": response_message}
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail="I'm having trouble understanding that. Could you try saying something like: 'My name is John and I fish on Long Island Sound'"
        )

@app.get("/test/route")
def read_root() -> dict[str, str]:
    return {
        "message": "Hello, We are going to tell ya when the best times to fish for striped bass are based on the moon and the tides if that's ok with you"
    }

@app.post("/agent/take-note")
async def take_note(request: Request) -> dict[str, str]:
    request_body = await request.json()
    if save_note(request_body['note']):
        return {"status": "success"}
    else:
        return {"status": "error"}

@app.post("/agent/search")
async def search(request: Request) -> dict[str, str]:
    request_body = await request.json()
    result = search_from_query(request_body['search_query'])
    return {
        "result": result
    }

@app.get("/agent/get-note")
async def get_note(request: Request) -> dict[str, str]:
    note = get_note_from_db()

    return {
        "note": note
    }

@app.get("/fishing-conditions/{first_name}")
async def get_fishing_conditions(first_name: str) -> dict:
    # Get user's saved location
    user_info = get_latest_user_info(first_name)
    if not user_info:
        raise HTTPException(status_code=404, message=f"No information found for {first_name}")
    
    # Get NOAA station data for the location
    station_data = get_noaa_station_data(user_info["fishing_location"])
    if not station_data:
        return {
            "message": f"Hey {first_name}, I don't have tide information for {user_info['fishing_location']} yet. "
                      "I currently support Cape Cod, Boston Harbor, New York Harbor, Chesapeake Bay, and Long Island Sound. "
                      "Please try one of these locations!"
        }
    
    # Get tide predictions for next 3 days
    start_date = datetime.now().strftime("%Y%m%d")
    end_date = (datetime.now() + timedelta(days=3)).strftime("%Y%m%d")
    
    tide_data = get_tide_predictions(
        station_data["stations"][0]["id"],
        start_date,
        end_date
    )
    
    if not tide_data or "predictions" not in tide_data:
        return {
            "message": f"Sorry {first_name}, I'm having trouble getting the tide predictions right now. Please try again later!"
        }
    
    # Format a fishing-focused response
    tides = tide_data["predictions"]
    next_tides = tides[:4]  # Get next 2 high and low tides
    
    response_message = (
        f"Hey {first_name}! Here's your striped bass fishing forecast for {user_info['fishing_location']}:\n\n"
        "Grandpa Spuds here, and let me tell you about the next few tides:\n\n"
    )
    
    for tide in next_tides:
        tide_time = datetime.strptime(tide["t"], "%Y-%m-%d %H:%M")
        response_message += f"- {tide['type']} tide at {tide_time.strftime('%I:%M %p')} ({tide['v']} ft)\n"
    
    response_message += "\nPro tip from Grandpa Spuds: Striped bass often feed most actively during tide changes, "
    response_message += "especially during the first two hours of an incoming tide or the last two hours of an outgoing tide. "
    response_message += "The low-light periods around dawn and dusk combined with these tide times are your best bet!"
    
    return {"message": response_message}
