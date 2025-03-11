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
        
        # Extract first name and fishing location from request body
        first_name = request_body.get('name', '')
        fishing_location = request_body.get('location', '')
        
        logger.info(f"Extracted first_name: {first_name}, fishing_location: {fishing_location}")
        
        # Validate the data
        if not first_name or not fishing_location:
            logger.error("Missing required fields")
            raise HTTPException(
                status_code=400,
                detail="Please provide both your first name and fishing location"
            )
        
        # Try to save user info to database
        logger.info("Attempting to save user info to database")
        save_result = save_user_info(first_name, fishing_location)
        logger.info(f"Save result: {save_result}")
        
        if save_result:
            response_message = f"Hey {first_name}! Great to meet you. I know {fishing_location} well - that's a fine spot for striped bass fishing. Let me help you figure out the best times to fish there based on the moon and tides."
            logger.info(f"Successfully processed request. Returning message: {response_message}")
            return {
                "message": response_message
            }
        else:
            logger.error("Failed to save user information")
            raise HTTPException(
                status_code=500,
                detail="Failed to save user information to database"
            )
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON format in request body"
        )
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred while processing your information. Please try again."
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
