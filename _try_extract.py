import json, sys, os
sys.path.insert(0, os.path.abspath('.'))
sys.path.insert(0, os.path.abspath('CBR'))
from helpers import ask_llm_extract

paragraph = (
    "The Train Ticket Reservation system is designed to facilitate the entire process of purchasing train tickets, "
    "from selecting a destination and origin, choosing between different seat classes and available trains, making payments, "
    "receiving payment confirmation, logging into an online booking platform, issuing tickets, and showing alternative options for travel."
)
res = ask_llm_extract(paragraph)
print(json.dumps(res, indent=2, ensure_ascii=False))