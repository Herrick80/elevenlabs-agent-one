from pymongo.synchronous.mongo_client import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
import logging

from typing import Any, Dict, Optional


import os
from dotenv import load_dotenv
from pymongo import DESCENDING, MongoClient
import requests
import datetime

_ = load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MONGO_URI: str | None = os.getenv("MONGODB_URI")

try:
    if not MONGO_URI:
        raise ValueError("MONGODB_URI environment variable is not set")
    
    client = MongoClient(MONGO_URI)
    # Test the connection
    client.admin.command('ping')
    db = client['eleven_labs_assistant']
    notes_collection = db['notes']
    users_collection = db['users']
    logger.info("Successfully connected to MongoDB")
except (ConnectionFailure, OperationFailure, ValueError) as e:
    logger.error(f"Failed to connect to MongoDB: {str(e)}")
    # Initialize to None so we can check if DB is available
    client = None
    db = None
    notes_collection = None
    users_collection = None

def save_user_info(first_name: str, fishing_location: str) -> bool:
    try:
        if not users_collection:
            logger.error("Database connection not available")
            return False
            
        result = users_collection.insert_one({
            "first_name": first_name,
            "fishing_location": fishing_location,
            "created_at": datetime.datetime.utcnow()
        })
        success = bool(result.inserted_id)
        logger.info(f"Successfully saved user info: {success}")
        return success
    except Exception as e:
        logger.error(f"Error saving user info: {str(e)}")
        return False

def save_note(note: str) -> bool:
    result = notes_collection.insert_one({"note": note})
    if result.inserted_id:
        return True
    else:
        return False

def get_note_from_db() -> str:
    last_doc = notes_collection.find_one(sort=[("_id", DESCENDING)])
    if last_doc:
        return last_doc['note']
    else:
        return "couldn't find any relevant note"

#   const body = {
#     model: metaData?.model || "llama-3.1-sonar-large-128k-online", // Specify the model
#     messages: [
#       { role: "system", content: "You are an AI assistant." },
#       { role: "user", content: prompt },
#     ],
#     max_tokens: 1024,
#     // temperature: 0.7
#   };

def query_perplexity(query: str):
    url = "https://api.perplexity.ai/chat/completions"

    
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {os.getenv("PERPLEXITY_API_KEY")}",
        "Content-Type": "application/json",
    }
    data = {
        "model": "sonar",
        "messages": [
            { "role": "system", "content": "You are an AI assistant." },
            { "role": "user", "content": query },
        ],
        "max_tokens": 1024,
    }

    response = requests.post(url, headers=headers, json=data)
    citations = response.json()['citations']
    output = response.json()['choices'][0]['message']['content']
    return output

def search_from_query(note: str) -> str:
    result = query_perplexity(note)

    if result:
        return result
    else:
        return "couldn't find any relevant note"

def get_latest_user_info(first_name: str) -> Optional[Dict]:
    user = users_collection.find_one(
        {"first_name": first_name},
        sort=[("created_at", DESCENDING)]
    )
    return user

def get_noaa_station_data(location: str) -> Optional[Dict]:
    """
    Get NOAA station data for a given location.
    For now, we'll use a simple mapping of locations to station IDs.
    In a production environment, this should be replaced with a more sophisticated
    location to station ID mapping system.
    """
    # Simple mapping of locations to NOAA station IDs
    station_mapping = {
        "cape cod": "8447930",  # Woods Hole, MA
        "boston harbor": "8443970",  # Boston, MA
        "new york harbor": "8518750",  # The Battery, NY
        "chesapeake bay": "8575512",  # Baltimore, MD
        "long island sound": "8516945",  # Kings Point, NY
    }
    
    # Convert location to lowercase and find closest match
    location_lower = location.lower()
    station_id = None
    for key in station_mapping:
        if key in location_lower:
            station_id = station_mapping[key]
            break
    
    if not station_id:
        return None
    
    # Make request to NOAA API
    url = f"https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/{station_id}.json"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None

def get_tide_predictions(station_id: str, start_date: str, end_date: str) -> Optional[Dict]:
    """
    Get tide predictions for a specific station and date range.
    """
    url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
    
    params = {
        "station": station_id,
        "begin_date": start_date,
        "end_date": end_date,
        "product": "predictions",
        "datum": "MLLW",
        "units": "english",
        "time_zone": "lst_ldt",
        "format": "json",
        "interval": "hilo"  # Get only high and low tides
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None
