from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, validator
from datetime import datetime, timedelta
import logging
import json

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
        # Get the raw request data and log it
        request_body = await request.json()
        logger.info(f"Received request body: {json.dumps(request_body)}")
        
        # Extract the message from various possible fields
        message = None
        if isinstance(request_body, dict):
            message = (
                request_body.get('text') or 
                request_body.get('message') or 
                request_body.get('input') or 
                request_body.get('query')
            )
        if not message and isinstance(request_body, (str, dict)):
            message = str(request_body)
        
        if not message:
            raise HTTPException(
                status_code=400,
                detail="I couldn't find any message in your request. Could you please tell me your name and where you'd like to fish?"
            )
            
        logger.info(f"Processing message: {message}")
        
        # Extract name and location using various patterns
        first_name = None
        fishing_location = None
        
        # Extract name
        message_lower = message.lower()
        if "name is" in message_lower:
            name_part = message_lower.split("name is")[1]
            # Split on common separators
            for separator in ["and", ",", ".", "i"]:
                if separator in name_part:
                    name_part = name_part.split(separator)[0]
            first_name = name_part.strip().title()
        
        # Extract location
        if "fish" in message_lower:
            if "on" in message_lower:
                loc_part = message_lower.split("on")[1]
            elif "in" in message_lower:
                loc_part = message_lower.split("in")[1]
            elif "at" in message_lower:
                loc_part = message_lower.split("at")[1]
            
            if loc_part:
                # Handle location with state
                parts = loc_part.strip().split(",")
                fishing_location = parts[0].strip().title()
                if len(parts) > 1:
                    fishing_location += ", " + parts[1].strip().title()
        
        logger.info(f"Extracted first_name: {first_name}, fishing_location: {fishing_location}")
        
        # Validate the extracted data
        if not first_name or not fishing_location:
            raise HTTPException(
                status_code=400,
                detail="I couldn't quite catch your name or fishing location. Could you please tell me your name and where you'd like to fish? For example: 'My name is John and I like to fish on Cape Cod'"
            )
        
        # Try to save to database but don't fail if it doesn't work
        try:
            save_result = save_user_info(first_name, fishing_location)
            if not save_result:
                logger.warning("Failed to save user info but continuing with response")
        except Exception as e:
            logger.error(f"Database error: {str(e)}")
            # Continue even if database save fails
        
        # Construct response message
        response_message = f"Hey {first_name}! Great to meet you. I know {fishing_location} well - that's a fine spot for striped bass fishing. Let me help you figure out the best times to fish there based on the moon and tides."
        
        logger.info(f"Returning message: {response_message}")
        return {"message": response_message}
            
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail="I couldn't understand the message format. Could you try telling me your name and where you'd like to fish again? For example: 'My name is John and I like to fish on Cape Cod'"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Something went wrong, but don't worry! Could you try telling me your name and where you'd like to fish one more time? For example: 'My name is John and I like to fish on Cape Cod'"
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
