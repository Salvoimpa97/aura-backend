import os
import json
import urllib.request
import urllib.error
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import pymongo
import certifi

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

if MONGO_URI:
    ca = certifi.where()
    client = pymongo.MongoClient(MONGO_URI, tlsCAFile=ca)
    db = client.aurafitness
else:
    db = None

def call_gemini(prompt):
    if not GEMINI_API_KEY:
        raise Exception("API Key mancante su Vercel")
    
    # Lista di modelli dal più recente/economico al più vecchio
    models = ['gemini-1.5-flash', 'gemini-1.5-flash-latest', 'gemini-1.5-pro', 'gemini-1.0-pro', 'gemini-pro']
    last_err = ""
    
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        req = urllib.request.Request(url, json.dumps(data).encode('utf-8'), headers)
        
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                res_data = json.loads(response.read().decode())
                return res_data['candidates'][0]['content']['parts'][0]['text'], model
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8')
            last_err = f"{model} -> HTTP {e.code}: {err_body}"
            # Se è 404 (non trovato) o 400 (bad request per modello non supportato), passa al successivo
            if e.code in [404, 400]:
                continue
            else:
                raise Exception(last_err)
        except Exception as e:
            last_err = str(e)
            continue
            
    raise Exception(f"Tutti i tentativi falliti. Ultimo errore: {last_err}")

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
    return {"status": "ok", "message": "Backend REST puro attivo!"}

@app.get("/api/test-chiave")
def test_chiave():
    if not GEMINI_API_KEY:
        return {"TEST FALLITO": "La variabile GEMINI_API_KEY non esiste su Vercel."}
    
    try:
        testo, modello_usato = call_gemini("Rispondi solo con la parola: FUNZIONA")
        return {
            "TEST SUPERATO": "Google Gemini risponde correttamente!",
            "Modello Funzionante": modello_usato,
            "Risposta": testo.strip()
        }
    except Exception as e:
        return {
            "TEST FALLITO": "Nessun modello ha funzionato.",
            "Dettaglio Errore": str(e)
        }

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
    prompt = f"Crea una scheda di allenamento per: {req.prompt}. Rispondi SOLO in JSON strutturato così: {{\"name\": \"Nome\", \"focus\": \"Focus\", \"exercises\": [{{\"name\": \"Esercizio\", \"muscle_group\": \"Gruppo\", \"sets\": 3, \"reps\": \"10\", \"rest\": \"60s\"}}]}}"
    
    try:
        res_text, _ = call_gemini(prompt)
    except Exception as e:
        raise HTTPException(500, f"Errore Gemini REST: {e}")

    if "```json" in res_text: res_text = res_text.split("```json")[1].split("```")[0]
    elif "```" in res_text: res_text = res_text.split("```")[1].split("```")[0]
    
    try:
        data = json.loads(res_text.strip())
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
    prompt = f"Crea una dieta per: {req.prompt}. Rispondi SOLO in JSON strutturato così: {{\"name\": \"Nome Dieta\", \"daily_calories\": 2000, \"protein_g\": 150, \"carbs_g\": 200, \"fat_g\": 60, \"meals\": [{{\"meal\": \"Colazione\", \"name\": \"Pancake proteici\", \"calories\": 400, \"items\": [{{\"name\": \"Avena 50g\", \"calories\": 180}}]}}]}}"
    
    try:
        res_text, _ = call_gemini(prompt)
    except Exception as e:
        raise HTTPException(500, f"Errore API Google Gemini: {e}")

    if "```json" in res_text: res_text = res_text.split("```json")[1].split("```")[0]
    elif "```" in res_text: res_text = res_text.split("```")[1].split("```")[0]
    
    try:
        data = json.loads(res_text.strip())
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
    if not db: raise HTTPException(500, "DB non connesso")
    db.chat.insert_one(msg.model_dump())
    prompt = f"Sei Aura, un personal trainer esperto e motivante. Rispondi in italiano, in modo conciso ed elegante a questo utente: {msg.content}"
    
    try:
        ai_response_text, _ = call_gemini(prompt)
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
