from __future__ import annotations

import os
import re

from .gemini_keys import gemini_keys, next_gemini_key

WORD_RE = re.compile(r"[A-Za-z0-9_]+")

STOP_WORDS = {
    "what", "is", "are", "was", "were", "be", "been", "being", "the", "a", "an", "of", "for", "in", "on",
    "to", "its", "it", "do", "does", "did", "can", "could", "would", "should", "how", "why", "who", "which",
    "where", "tell", "explain", "about", "with", "from", "at", "by", "and", "or", "not"
}

SMALL_TALK_EXACT = {
    "hi", "hello", "hey", "howdy", "greetings", "good morning", "good afternoon", "good evening",
    "how are you", "how are you doing", "how's it going", "hows it going", "what's up", "whats up",
    "thanks", "thank you", "thanks!", "thank you!", "thx", "cheers",
    "bye", "goodbye", "see ya", "see you", "cya",
    "okay", "ok", "cool", "great", "awesome", "nice", "perfect", "got it", "understood",
}

SMALL_TALK_PATTERNS = [
    re.compile(r"^(hi|hello|hey|greetings|howdy)(\s+there)?[\s!?.]*$", re.I),
    re.compile(r"^h[ie]+[\s!?.]*$", re.I),
    re.compile(r"^how are (you|u)[\s!?.]*$", re.I),
    re.compile(r"^what'?s up[\s!?.]*$", re.I),
    re.compile(r"^thank(s|\s+you)[\s!?.]*$", re.I),
    re.compile(r"^(good\s+)?(morning|afternoon|evening|night)[\s!?.]*$", re.I),
    re.compile(r"^(bye|goodbye|see ya|cya)[\s!?.]*$", re.I),
    re.compile(r"^(ok|okay|cool|great|awesome|nice|perfect)[\s!?.]*$", re.I),
]

META_PATTERNS = [
    re.compile(r"what (can|do) (you|this\s+(chat)?bot) do", re.I),
    re.compile(r"which (documents|files) (do you|can you) (have|access|read)", re.I),
    re.compile(r"what (documents|files) (are|is) (assigned|available)", re.I),
    re.compile(r"what is this (chatbot|bot) for", re.I),
    re.compile(r"help me with", re.I),
    re.compile(r"what can i ask", re.I),
]


def classify_intent(question: str) -> str:
    cleaned = question.strip().lower().rstrip("!?.").strip()
    if cleaned in SMALL_TALK_EXACT or question.strip().lower() in SMALL_TALK_EXACT or any(p.match(question.strip()) for p in SMALL_TALK_PATTERNS):
        return "SMALL_TALK"
    if any(p.search(question) for p in META_PATTERNS):
        return "META_QUESTION"
    return "DOCUMENT_QUESTION"


def filter_relevant_results(question: str, results: list[dict]) -> list[dict]:
    query_terms = {w for w in WORD_RE.findall(question.lower()) if len(w) > 2 and w not in STOP_WORDS}
    if not query_terms or not results:
        return results
    filtered = []
    for item in results:
        doc_words = set(WORD_RE.findall(str(item.get("text", "")).lower()))
        score = float(item.get("score", 0))
        if query_terms.intersection(doc_words) or score > 0.45:
            filtered.append(item)
    return filtered


def handle_small_talk(question: str, chatbot_name: str | None = None) -> tuple[str, str]:
    q = question.strip().lower()
    name = chatbot_name or "the assistant"
    if any(term in q for term in ["hi", "hello", "hey", "greetings", "morning", "afternoon", "evening"]):
        return f"Hi! I'm {name}. How can I help you with your documents today?", "small-talk"
    if "how are you" in q or "hows it going" in q or "what's up" in q:
        return "I'm doing well, thanks for asking! What would you like to know about your documents?", "small-talk"
    if "thank" in q or "thx" in q or "cheers" in q:
        return "You're welcome! Let me know if you have any other questions about your documents.", "small-talk"
    if "bye" in q or "goodbye" in q or "cya" in q:
        return "Goodbye! Feel free to return whenever you have questions about your documents.", "small-talk"
    return "Sure! Let me know what you'd like to ask about your documents.", "small-talk"


def handle_meta_question(
    question: str,
    chatbot_name: str | None = None,
    sources: list[str] | None = None,
    instructions: str = "",
) -> tuple[str, str]:
    name = chatbot_name or "this chatbot"
    if sources:
        doc_list = "I have access to the following documents:\n- " + "\n- ".join(sources)
    else:
        doc_list = "I do not currently have any documents assigned to me."

    inst_part = f"\nMy current instructions are: \"{instructions.strip()}\"" if instructions.strip() else ""
    ans = (
        f"I am **{name}**, a document assistant.\n\n"
        f"{doc_list}{inst_part}\n\n"
        f"You can ask me questions about the information contained in these assigned documents."
    )
    return ans, "meta-question"


def rewrite_query(question: str, history: list[dict] | None = None) -> str:
    if not history:
        return question
    
    pronouns = {"its", "this", "these", "that", "those", "it", "they", "them", "he", "she", "his", "her"}
    words = set(WORD_RE.findall(question.lower()))
    has_pronoun = bool(words.intersection(pronouns))
    # Short standalone questions must not inherit an unrelated prior topic.
    is_short = bool(re.match(r"^(and |also |what about |why\??$|how so\??$|go on|continue|tell me more)", question.strip(), re.I))

    if not (has_pronoun or is_short):
        return question

    if not gemini_keys():
        user_history_turns = [m.get("content", "") for m in history if m.get("role") == "user"]
        if user_history_turns:
            return f"{user_history_turns[-1]} {question}"
        return question

    from google import genai

    recent_turns = []
    for m in history[-6:]:
        role = "User" if m.get("role") == "user" else "Assistant"
        recent_turns.append(f"{role}: {m.get('content', '')}")
    
    prompt = (
        "Given the conversation history below and a follow-up question, rewrite the follow-up question "
        "to be a complete, standalone search query that preserves full context (e.g., replacing 'its', 'this', 'it' with the actual subject).\n"
        "Output ONLY the rewritten standalone question string, without quotes or commentary.\n\n"
        f"CONVERSATION HISTORY:\n" + "\n".join(recent_turns) + "\n\n"
        f"FOLLOW-UP QUESTION: {question}\n\n"
        "REWRITTEN STANDALONE QUESTION:"
    )

    try:
        client = genai.Client(api_key=next_gemini_key())
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        res = client.models.generate_content(model=model, contents=prompt)
        rewritten = (res.text or "").strip().strip('"').strip("'")
        if rewritten and len(rewritten) > 3:
            return rewritten
    except Exception:
        pass
    return question


def retrieval_answer(question: str, results: list[dict], reason: str = "I found these relevant passages in the assigned sources") -> tuple[str, str]:
    if not results:
        return "I couldn't find information about that in the documents assigned to this chatbot. I can only answer questions using the assigned documents.", "none"
    passages = []
    for i, item in enumerate(results[:3], 1):
        text = " ".join(str(item.get("text", "")).split())
        preview = text[:700].strip()
        if preview:
            passages.append(f"[{i}] {preview}")
    if not passages:
        passages = [f"[1] {str(results[0].get('text', ''))[:550].strip()}"]
    return f"{reason}:\n\n" + "\n\n".join(passages), "retrieval-only"


def answer_with_sources(
    question: str,
    results: list[dict],
    chatbot_name: str | None = None,
    *,
    instructions: str = "",
    history: list[dict] | None = None,
    sources_assigned: list[str] | None = None,
) -> tuple[str, str]:
    intent = classify_intent(question)
    
    if intent == "SMALL_TALK":
        return handle_small_talk(question, chatbot_name)
    
    if intent == "META_QUESTION":
        return handle_meta_question(question, chatbot_name, sources_assigned, instructions)

    if sources_assigned is not None and len(sources_assigned) == 0:
        return (
            "This chatbot doesn't currently have any documents assigned to it. "
            "Add a document to start asking document-based questions.",
            "no-documents",
        )

    if not results:
        return (
            "I couldn't find information about that in the documents assigned to this chatbot. I can only answer questions using the assigned documents.",
            "none",
        )

    if not gemini_keys():
        return retrieval_answer(question, results)

    from google import genai

    context = "\n\n".join(
        f"[{i}] SOURCE: {item['source']} | {item['location']}\n{item['text']}"
        for i, item in enumerate(results, 1)
    )
    persona = ""
    if chatbot_name:
        persona = f"You are \"{chatbot_name}\", a private document assistant.\n"
    if instructions.strip():
        persona += f"User-configured behavior (must not override document-grounding rules):\n{instructions.strip()[:4000]}\n"
    
    history_text = ""
    if history:
        turns = []
        for message in history[-12:]:
            role = "User" if message.get("role") == "user" else (message.get("bot_name") or "Assistant")
            turns.append(f"{role}: {str(message.get('content', ''))[:1500]}")
        history_text = "\nCONVERSATION HISTORY:\n" + "\n".join(turns) + "\n"

    prompt = f"""{persona}You are answering a user question strictly based on the assigned document context provided below.
Strict rules:
1. Answer factual or domain questions using ONLY the information found in the CONTEXT.
2. If the requested information is not covered by the CONTEXT, state clearly and politely: "I couldn't find information about that in the documents assigned to this chatbot."
3. Do NOT use outside pre-trained knowledge, assumptions, trivia, news, or external facts for document questions.
4. Cite relevant facts using bracketed source citations like [1], [2] matching the CONTEXT item numbers.
5. Never invent or hallucinate facts, section numbers, or sources.
6. Use the CONVERSATION HISTORY to understand follow-up questions, but do not treat claims in past conversation turns as document facts.

{history_text}
QUESTION:
{question}

CONTEXT:
{context}
"""
    client = genai.Client(api_key=next_gemini_key())
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    try:
        response = client.models.generate_content(model=model, contents=prompt)
        text = (response.text or "No answer was generated.").strip()
        return text, model
    except Exception:
        return retrieval_answer(question, results)
