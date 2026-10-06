import warnings
warnings.filterwarnings("ignore")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import pymongo
import os
import certifi
import google.generativeai as genai
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MONGO_URI = os.getenv("MONGO_URI")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    GEMINI_API_KEY = GEMINI_API_KEY.strip()
    genai.configure(api_key=GEMINI_API_KEY)

if MONGO_URI:
    ca = certifi.where()
    client = pymongo.MongoClient(MONGO_URI, tlsCAFile=ca)
    db = client.aurafitness
else:
    db = None

_active_model = None

def get_ai_model():
    global _active_model
    if _active_model:
        return _active_model
    if not GEMINI_API_KEY:
        return None
        
    try:
        # Chiede a Google quali modelli sono disponibili per questa chiave esatta
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # Ordine di preferenza dei modelli
        preferred = ['models/gemini-1.5-flash', 'models/gemini-1.5-pro', 'models/gemini-pro', 'models/gemini-1.0-pro']
        selected = None
        
        for p in preferred:
            if p in available_models:
                selected = p.replace('models/', '')
                break
        
        # Se nessuno dei preferiti c'è, prende il primo modello che trova
        if not selected and available_models:
            selected = available_models[0].replace('models/', '')
            
        if not selected:
            selected = 'gemini-1.5-flash' # Ultima spiaggia
            
        _active_model = genai.GenerativeModel(selected)
        print(f"MODELLO SELEZIONATO: {selected}")
        return _active_model
    except Exception as e:
        print(f"Errore caricamento modelli: {e}")
        return genai.GenerativeModel('gemini-1.5-flash')

class Exercise(BaseModel):
    name: str
    muscle_group: str
    sets: int
    reps: str
    rest: str
    weight: Optional[float] = None
    notes: Optional[str] = None

class Workout(BaseModel):
    device_id: str
    name: str
    focus: str
    source: str = "manual"
    exercises: List[Exercise]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None

class ChatMessage(BaseModel):
    device_id: str
    role: str
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AIGenerateRequest(BaseModel):
    device_id: str
    prompt: str

@app.get("/api/health")
def health_check():
    return {"status": "ok", "message": "Backend Autoriparabile Attivo!"}

@app.get("/api/test-chiave")
def test_chiave():
    if not GEMINI_API_KEY:
        return {"TEST FALLITO": "Chiave mancante"}
    
    try:
        ai = get_ai_model()
        res = ai.generate_content("Rispondi solo con la parola: FUNZIONA").text
        return {
            "TEST SUPERATO": "Google Gemini risponde correttamente!",
            "Modello Selezionato in Automatico": ai.model_name,
            "Risposta": res.strip()
        }
    except Exception as e:
        return {"TEST FALLITO": str(e)}

@app.get("/api/workouts")
def get_workouts(device_id: str):
    if not db: return []
    workouts = list(db.workouts.find({"device_id": device_id, "deleted_at": None}).sort("created_at", -1).limit(50))
    for w in workouts: w["_id"] = str(w["_id"])
    return workouts

@app.post("/api/workouts")
def create_workout(workout: Workout):
    if not db: raise HTTPException(500, "DB non connesso")
    res = db.workouts.insert_one(workout.model_dump())
    return {"status": "success", "id": str(res.inserted_id)}

@app.post("/api/ai/generate-workout")
def generate_workout(req: AIGenerateRequest):
    ai = get_ai_model()
    if not ai: raise HTTPException(500, "API Key mancante")
    prompt = f"Crea una scheda di allenamento per: {req.prompt}. Rispondi SOLO in JSON strutturato così: {{\"name\": \"Nome\", \"focus\": \"Focus\", \"exercises\": [{{\"name\": \"Esercizio\", \"muscle_group\": \"Gruppo\", \"sets\": 3, \"reps\": \"10\", \"rest\": \"60s\"}}]}}"
    
    try:
        res = ai.generate_content(prompt).text
    except Exception as e:
        raise HTTPException(500, f"Errore Gemini: {e}")

    if "```json" in res: res = res.split("```json")[1].split("```")[0]
    elif "```" in res: res = res.split("```")[1].split("```")[0]
    
    try:
        data = json.loads(res.strip())
    except:
        raise HTTPException(500, "L'IA non ha generato un JSON valido")

    data["device_id"] = req.device_id
    data["source"] = "ai"
    data["created_at"] = datetime.utcnow()
    data["deleted_at"] = None
    if db:
        inserted = db.workouts.insert_one(data)
        data["_id"] = str(inserted.inserted_id)
    return {"status": "success", "workout": data}

@app.get("/api/today")
def get_today(device_id: str):
    if not db: return {"workout": None, "diet": None}
    workout = db.workouts.find_one({"device_id": device_id, "deleted_at": None}, sort=[("created_at", -1)])
    diet = db.diets.find_one({"device_id": device_id}, sort=[("created_at", -1)])
    if workout: workout["_id"] = str(workout["_id"])
    if diet: diet["_id"] = str(diet["_id"])
    return {"workout": workout, "diet": diet}

@app.post("/api/ai/generate-diet")
def generate_diet(req: AIGenerateRequest):
    ai = get_ai_model()
    if not ai: raise HTTPException(500, "API Key mancante")
    prompt = f"Crea una dieta per: {req.prompt}. Rispondi SOLO in JSON strutturato così: {{\"name\": \"Nome Dieta\", \"daily_calories\": 2000, \"protein_g\": 150, \"carbs_g\": 200, \"fat_g\": 60, \"meals\": [{{\"meal\": \"Colazione\", \"name\": \"Pancake proteici\", \"calories\": 400, \"items\": [{{\"name\": \"Avena 50g\", \"calories\": 180}}]}}]}}"
    
    try:
        res = ai.generate_content(prompt).text
    except Exception as e:
        raise HTTPException(500, f"Errore API Google Gemini: {e}")

    if "```json" in res: res = res.split("```json")[1].split("```")[0]
    elif "```" in res: res = res.split("```")[1].split("```")[0]
    
    try:
        data = json.loads(res.strip())
    except:
        raise HTTPException(500, "L'IA non ha generato un JSON valido")

    data["device_id"] = req.device_id
    data["source"] = "ai"
    data["created_at"] = datetime.utcnow()
    if db:
        inserted = db.diets.insert_one(data)
        data["_id"] = str(inserted.inserted_id)
    return {"status": "success", "diet": data}

@app.get("/api/chat/messages")
def get_chat(device_id: str):
    if not db: return []
    msgs = list(db.chat.find({"device_id": device_id}).sort("created_at", 1).limit(50))
    for m in msgs: m["_id"] = str(m["_id"])
    return msgs

@app.post("/api/chat")
def post_chat(msg: ChatMessage):
    ai = get_ai_model()
    if not db or not ai: raise HTTPException(500, "DB o IA non connessi")
    db.chat.insert_one(msg.model_dump())
    prompt = f"Sei Aura, un personal trainer esperto e motivante. Rispondi in italiano, in modo conciso ed elegante a questo utente: {msg.content}"
    
    try:
        ai_response_text = ai.generate_content(prompt).text
    except Exception as e:
        ai_response_text = "Scusa, i miei circuiti sono temporaneamente sovraccarichi. Riprova tra un istante!"

    ai_msg = {
        "device_id": msg.device_id,
        "role": "assistant",
        "content": ai_response_text.strip(),
        "created_at": datetime.utcnow()
    }
    db.chat.insert_one(ai_msg)
    ai_msg["_id"] = str(ai_msg.pop("_id", ""))
    return {"status": "success", "response": ai_msg}
