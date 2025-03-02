from pymongo.synchronous.mongo_client import MongoClient


from typing import Any


import os
from dotenv import load_dotenv
from pymongo import DESCENDING, MongoClient
import requests

_ = load_dotenv()

MONGO_URI: str | None = os.getenv("MONGODB_URI")    
client = MongoClient(MONGO_URI)
db = client['eleven_labs_assistant']
notes_collection = db['notes']

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
