from chatbot.models import FAQ

faqs = [

("book now", "book",
"Great 🎉\n👉 Share your name", "trust"),

("i want to book", "want book",
"Awesome 😊\n👉 Your name?", "trust"),

("call me", "call",
"Sure 😊\n👉 Mobile number?", "trust"),

("connect to agent", "agent",
"Connecting 😊\n👉 Name please", "trust"),

("talk to expert", "expert",
"Sure 😊\n👉 Name?", "trust"),

("schedule call", "schedule",
"Done 😊\n👉 Number?", "trust"),

("ready to book", "ready",
"Great 🔥\n👉 Name?", "trust"),

("proceed booking", "proceed",
"Let’s go 😊\n👉 Name?", "trust"),

("confirm booking", "confirm",
"Almost done 🎉\n👉 Number?", "trust"),

("contact me", "contact",
"Sure 😊\n👉 Mobile?", "trust"),

("start booking", "start",
"Great 😊\n👉 Name?", "trust"),

("book package", "package",
"Awesome 😊\n👉 Name?", "trust"),

("i am ready", "ready",
"Perfect 😊\n👉 Name?", "trust"),

("finalize booking", "finalize",
"Done 😊\n👉 Mobile?", "trust"),

("get call", "call",
"Sure 😊\n👉 Number?", "trust"),

("need callback", "callback",
"Okay 😊\n👉 Mobile?", "trust"),

("connect expert", "expert",
"Sure 😊\n👉 Name?", "trust"),

("talk now", "talk",
"Let’s connect 😊\n👉 Number?", "trust"),

("book trip", "trip",
"Great 😊\n👉 Name?", "trust"),

("start process", "process",
"Let’s start 😊\n👉 Name?", "trust"),

("continue booking", "continue",
"Sure 😊\n👉 Mobile?", "trust"),

("yes i want", "yes",
"Great 😊\n👉 Name?", "trust"),

("interested", "interested",
"Awesome 😊\n👉 Name?", "trust"),

("proceed", "proceed",
"Sure 😊\n👉 Name?", "trust"),

("lets book", "book",
"Done 😊\n👉 Mobile?", "trust"),

]

for q,k,a,c in faqs:
    FAQ.objects.get_or_create(question=q, defaults={"keywords":k,"answer":a,"category":c})

print("✅ Trust Script 4 Done")