# AI Log

## Instances that I Avoided

I asked Claude to suggest a way to match the event that triggered vs fanning them out to its correct subscribers. 
It made assumptions which were an overkill for example it assumed that we would have order.created / user.signup now for such a simple use case we should just have a string as an event and compare it against what the subscriber wanted. 

Prompt - "I am not happy with having no exhaustive list of Events that should be a contract known to subscribers who are using the webhook service. Can we set an exhaustive list of say Events from A to Z that the user can send ? The matching logic should also be simple in that case"

Reply : 

```python
from enum import Enum

class EventType(str, Enum):
    ORDER_CREATED     = "order.created"
    ORDER_UPDATED     = "order.updated"
    ORDER_CANCELLED   = "order.cancelled"
    ORDER_SHIPPED     = "order.shipped"
    USER_SIGNUP       = "user.signup"
    USER_DELETED      = "user.deleted"
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED    = "payment.failed"

ALL_EVENT_TYPES = [e.value for e in EventType]

from matching import filter_matches

def test_matching():
    assert filter_matches("order.created", "order.created") is True
    assert filter_matches("order.created", "order.*")       is True
    assert filter_matches("order.created", "user.*")        is False
    assert filter_matches("order.created", "*")             is True
```

Going into Enums was an overkill in my opinion and not required , instead I just used a simple "==" check . Although unit testing is a very important part of SDLC but not required here. 

---

## Instances that I kept from claude

When I had to deploy the dashboard , I asked it to build the dashboard based on the APIs that I had built in the BE. It gave me simple html pages that could be rendered for testing that I have submitted in the code. I have decided to keep those. Claude suggested auto refresh but I decided not to implement those as we are not building a real webhook service but rather only a lite version to test out a few things. 

Same goes for getting the Dockerfile and the docker-compse.yaml file. 

---

## Instance where I added more than what claude suggested

So Claude had suggested keeping only a fake_subscriper.py file that goes down occasionally and comes back in but It missed the creation of a benign and unreachable client. Which I had to add .

Claude suggestion - 

Piece 1 — a fake subscriber to deliver to (fake_subscriber.py)
You need something on the other end that you can misbehave on purpose. This little app fails the first two times it sees an event, then succeeds — perfect for watching retries work:
Code ….
Run it in its own terminal: uvicorn fake_subscriber:app --port 9000. It's faking a flaky server — two failures, then a success — so you can see the whole retry-then-deliver arc.

What I added - used the same code and modified to behave like a benign and unreachable client. 

---

## Files + Module Organization

According to Claude this entire project could be split into 3 files alone that is main.py , worker.py and subscribers.py but that is not at all readable and looks cluttered. So I had to split functions across modules and files by myself and fix all the import issues. 

Plus all the hyperparameters such as MAX_ATTEMPS , POLL_FREQUENCY etc were not config driven so in future if anyone had to change these , then they will have to manually go to each file and change it which is not a good practice, so I had to make the code config driven. 

Plus On  running the docker compose up –build command you always had to manually navigate to the /dashboard url to see the actual dashboard a simple redirect from root to /dashboard url was needed. 

---

## Another instance where I agreed to what claude returned

So all the atomic cases like marking deliveries failed on reaching max attempts + marking them as delivered / in_progress were just simple atomic functions and a simple update query to db so I had used them straight away from claude because it did a fairly straight forward job in implementing them. 
