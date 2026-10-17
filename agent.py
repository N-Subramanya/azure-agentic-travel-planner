"""Agentic trip planner: GPT-4.1 decides which tools to call, in a loop, until it can answer."""
import json
import logging
from datetime import date, timedelta

import requests

MAX_STEPS = 6
HTTP_TIMEOUT = 10

SYSTEM_PROMPT = """You are the Konaseema Travels AI trip planner.

You can call tools to gather facts before answering:
- search_brochures: facts about destinations, attractions, hotels and package prices. Use it for anything destination-specific.
- get_weather: real weather data for a city (live forecast, or last year's figures for a given month).
- estimate_budget: rough trip cost in INR.

Rules:
- Use tools whenever they help. Call several tools if the question needs it.
- Base destination facts ONLY on search_brochures results. If the brochures don't cover something, say so.
- Pass a city or town plus its country code to get_weather (e.g. "Leh"/"IN" for Ladakh, "Alappuzha"/"IN" for Kerala backwaters).
- Keep answers practical and well structured (short headings, bullet points, day-by-day plans when asked).
- Never invent prices or facts that the tools did not return."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_brochures",
            "description": "Search the company's travel brochures for destination facts, attractions, hotels, packages and prices.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look up, e.g. 'Ladakh attractions and best time to visit'"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather for a city: a 7-day forecast, or daily averages for a month (based on last year's data).",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City or town name, e.g. 'Leh', 'Agra', 'Dubai'"},
                    "country_code": {"type": "string", "description": "ISO 3166-1 alpha-2 country code, e.g. 'IN', 'AE', 'GB', 'US'"},
                    "month": {"type": "integer", "minimum": 1, "maximum": 12, "description": "Month number for travel-month averages. Omit for the live 7-day forecast."},
                },
                "required": ["city", "country_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estimate_budget",
            "description": "Estimate a rough trip cost in INR (stay, food, local transport, activities). Excludes flights to the destination.",
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {"type": "string"},
                    "days": {"type": "integer", "minimum": 1},
                    "travellers": {"type": "integer", "minimum": 1},
                    "style": {"type": "string", "enum": ["budget", "mid", "luxury"]},
                },
                "required": ["destination", "days", "travellers"],
            },
        },
    },
]

# Per person, per day, in INR: stay, food, local transport, activities
DAILY_RATES_INR = {
    "budget": {"stay": 1500, "food": 800, "local_transport": 600, "activities": 600},
    "mid": {"stay": 4000, "food": 1500, "local_transport": 1200, "activities": 1300},
    "luxury": {"stay": 10000, "food": 3500, "local_transport": 2500, "activities": 3000},
}
INTERNATIONAL = ("dubai", "london", "new york", "las vegas", "san francisco")
INTERNATIONAL_MULTIPLIER = 2.5


class TripPlannerAgent:
    def __init__(self, client, deployment, search_fn):
        self.client = client
        self.deployment = deployment
        self.search_fn = search_fn

    # ---------------- tools ----------------

    def search_brochures(self, query, sources):
        results = self.search_fn(query)[:3]
        for r in results:
            source = {"title": r["title"], "url": r["metadata_storage_path"]}
            if source not in sources:
                sources.append(source)
        return [{"title": r["title"], "text": r["chunk"][:1500]} for r in results]

    def get_weather(self, city, country_code=None, month=None):
        params = {"name": city, "count": 5}
        if country_code:
            params["countryCode"] = country_code.upper()
        matches = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search", params=params, timeout=HTTP_TIMEOUT
        ).json().get("results", [])
        if not matches:
            return {"error": f"City '{city}' not found. Try a nearby city or town name."}
        # The geocoder is fuzzy ("Leh" → "Le Havre"): prefer an exact name match
        place = next((m for m in matches if m["name"].lower() == city.lower()), matches[0])
        daily = "temperature_2m_max,temperature_2m_min,precipitation_sum"
        location = {"latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto", "daily": daily}

        if month:
            year = date.today().year - 1
            start = date(year, month, 1)
            end = date(year + (month == 12), month % 12 + 1, 1)
            data = requests.get(
                "https://archive-api.open-meteo.com/v1/archive",
                params={**location, "start_date": start.isoformat(), "end_date": (end - timedelta(days=1)).isoformat()},
                timeout=HTTP_TIMEOUT,
            ).json()["daily"]
            n = len(data["time"])
            return {
                "place": f"{place['name']}, {place.get('admin1', '')}, {place.get('country', '')}",
                "period": f"{start.strftime('%B')} {year} (daily averages)",
                "avg_max_c": round(sum(data["temperature_2m_max"]) / n, 1),
                "avg_min_c": round(sum(data["temperature_2m_min"]) / n, 1),
                "rainy_days": sum(1 for p in data["precipitation_sum"] if (p or 0) >= 1),
            }

        data = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={**location, "forecast_days": 7},
            timeout=HTTP_TIMEOUT,
        ).json()["daily"]
        return {
            "place": f"{place['name']}, {place.get('admin1', '')}, {place.get('country', '')}",
            "forecast": [
                {"date": d, "max_c": hi, "min_c": lo, "rain_mm": rain}
                for d, hi, lo, rain in zip(data["time"], data["temperature_2m_max"], data["temperature_2m_min"], data["precipitation_sum"])
            ],
        }

    @staticmethod
    def estimate_budget(destination, days, travellers, style="mid"):
        rates = DAILY_RATES_INR.get(style, DAILY_RATES_INR["mid"])
        multiplier = INTERNATIONAL_MULTIPLIER if any(c in destination.lower() for c in INTERNATIONAL) else 1
        breakdown = {k: round(v * multiplier * days * travellers) for k, v in rates.items()}
        return {
            "destination": destination,
            "days": days,
            "travellers": travellers,
            "style": style,
            "breakdown_inr": breakdown,
            "total_inr": sum(breakdown.values()),
            "note": "Rough estimate from typical rates; excludes flights/trains to the destination.",
        }

    # ---------------- agent loop ----------------

    def _call_tool(self, name, args, sources):
        try:
            if name == "search_brochures":
                return self.search_brochures(args["query"], sources)
            if name == "get_weather":
                return self.get_weather(args["city"], args.get("country_code"), args.get("month"))
            if name == "estimate_budget":
                return self.estimate_budget(**args)
            return {"error": f"Unknown tool {name}"}
        except Exception as ex:
            logging.exception("Tool %s failed", name)
            return {"error": f"{name} failed: {type(ex).__name__}"}

    def run(self, question, history=None):
        """Returns (answer, steps, sources). history is a list of {"role", "content"} from earlier turns."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *(history or []), {"role": "user", "content": question}]
        steps, sources = [], []

        for _ in range(MAX_STEPS):
            response = self.client.chat.completions.create(
                model=self.deployment, messages=messages, tools=TOOLS, temperature=0.3
            )
            msg = response.choices[0].message
            if not msg.tool_calls:
                return msg.content, steps, sources

            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                result = self._call_tool(tc.function.name, args, sources)
                steps.append({"tool": tc.function.name, "args": args, "ok": not (isinstance(result, dict) and "error" in result)})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, ensure_ascii=False)})

        # Step limit reached: ask for a final answer without more tool calls
        response = self.client.chat.completions.create(
            model=self.deployment, messages=messages, tools=TOOLS, tool_choice="none", temperature=0.3
        )
        return response.choices[0].message.content, steps, sources
