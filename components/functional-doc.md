# Functional documentation

This document describes what the Ustad Hotel voice agent does for a customer. For how it works, see [architecture.md](architecture.md) and [technical-doc.md](technical-doc.md).

## Purpose

The agent takes food delivery orders by voice for Ustad Hotel, an Indian restaurant in Bangalore. The customer speaks in the browser. The agent replies by voice in English with an Indian English accent. It also answers questions about the menu, prices, allergens and shop policies.

## Users

- **Customer:** opens the web page, speaks to the agent and places an order.
- **Shop staff:** use the desk to read every conversation, choose the voice model, add customers, see each customer's orders, edit what the agent knows, and set the order steps. Read OTPs in the server log. Edit the menu and FAQ documents.

## Main flow: place an order

The agent follows these steps in order and asks one thing at a time. This is the default flow. Staff can change the order and add steps in the desk **Flow** section (see [Flow](#flow)).

1. **Greeting.** The agent speaks first: "Welcome to Ustad Hotel! May I know your name, please?"
2. **Name.** The customer gives a name. The agent saves it.
3. **Delivery address.** The agent asks for the address and city.
   - If the address is in Bangalore, the agent confirms delivery and continues.
   - If it is not in Bangalore, the agent apologizes and asks for a Bangalore address.
   - If the customer wants to give the address later, the agent explains that it must check delivery first, so the customer does not waste time.
4. **Order items.** The agent tells the customer about the starters first, then the meals. It adds each item the customer asks for. The agent does not take items before the address is checked.
5. **Read back.** The agent reads back the order and says: "Please note, once the order is placed it cannot be cancelled. Would you like to change anything?"
6. **Payment.** The customer chooses UPI or Credit Card. The agent does not accept other methods.
7. **Phone number.** The customer gives a 10-digit phone number. The agent saves it.
8. **OTP.** The agent sends a 4-digit OTP to that number and asks the customer to read it out.
   - If the OTP is correct, the order is confirmed and sent to the kitchen.
   - If the OTP is wrong, the agent asks again. After 3 wrong tries, the agent offers to send a new OTP.
9. **Thanks.** The agent thanks the customer by name.

## Business rules

| Rule | Detail |
|------|--------|
| Delivery area | Bangalore only (also "Bengaluru" or "BLR") |
| Address first | No items are taken before the address is checked |
| Payment methods | UPI or Credit Card only |
| Phone number | 10 digits. A `+91` prefix is accepted. |
| OTP | 4 digits, maximum 3 wrong tries |
| Confirmation | The order is confirmed only after a correct OTP |
| Cancellation | Allowed any time before the OTP confirms the order. Not allowed after. The phone number is kept for a new order. |
| Currency | All prices are in rupees and include GST |
| Delivery fee | ₹40, free for orders over ₹500 (from the FAQ) |
| Language | The agent replies in English only, also when the customer uses another language |

## Questions and answers

The customer can ask questions at any time. For questions about prices, ingredients, allergens, opening hours, delivery, payment or refunds, the agent searches the shop documents and answers only from them. If the documents do not have the answer, the agent says that it does not know.

Examples:

| Question | Source |
|----------|--------|
| "How much is the Chicken Mandi?" | `menu.md` |
| "Does Chicken 65 have gluten?" | `allergens.md` |
| "Is the korma nut free?" | `allergens.md` |
| "What time do you close on Sunday?" | `faq.md` |
| "Do you charge for delivery?" | `faq.md` |
| "Can I get a refund?" | `faq.md` |

To change these answers, shop staff edit the modules in the desk **Training** section. A change applies from the next question. See [Training](#training) and [rag_doc.md](rag_doc.md).

## Recommendations

When the customer asks what is best, the agent recommends the specials:

- Starter: Chicken 65
- Meals: Chicken Mandi or Mutton Biriyani

## Menu summary

- **Starters:** Chicken Kabab, Chilli Chicken, Chicken 65
- **Meals:** Chicken Biriyani, Mutton Biriyani, Chicken Mandi, Mutton Mandi, Mutton Korma with Butter Naan
- **Sandwiches:** turkey, ham or roast beef
- **Sandwich toppings:** lettuce, tomato, onion, pickles, mayo, mustard
- **Sandwich cheeses:** swiss, cheddar, provolone

Prices and details are in the **Menu** module on the desk. The first start copies them from `components/python/knowledge/menu.md`.

## Conversation behavior

- **Interruptions.** In the realtime mode, the customer can speak over the agent. The agent stops talking and listens. The `sandwich` and `ollama` modes do not support this.
- **Silence.** In the realtime mode, if the customer is silent for 8 seconds after the agent speaks, the agent asks "Hello, are you there?" one time.
- **Local mode.** In the `ollama` mode, a model on the shop's own computer replies. The customer hears the same greeting and steps. Replies take longer, about 2–5 seconds when the agent saves something.
- **Corrections.** Tool results tell the agent when something is missing or wrong, for example a missing address or an invalid phone number. The agent then asks the customer again.

## Desk

The desk is a separate page for shop staff. Open `http://localhost:8000/desk/`, or choose **Open Desk** at the top of the order page. On a wide screen the sections are in a sidebar. On a phone they are in a tab bar at the bottom.

### Conversations

- The list shows each call, newest first: the customer's name (or "Unknown caller"), the first thing they said, the time, the mode, and the result: **Live**, **Ordered**, **Cancelled** or **No order**.
- Select a call to read the transcript. The customer's words and the agent's words show as message bubbles. Each tool the agent used shows as a small line, for example "Added to order: Chicken 65, 2". Select the line to see the tool result.
- A live call updates every 2 seconds. The list updates every 5 seconds.
- Search finds calls by name, phone number or words the customer said.
- A call is saved when the customer first speaks. A session closed before the customer speaks is not saved.

### Customers

- **Add Customer.** Enter a name and a 10-digit phone number. If the number is already saved, the customer gets the new name.
- **All Customers.** Each customer shows the name, phone number, and the number of orders and items. Select a customer to see each order: status (confirmed or cancelled), date, mode, items, payment method and address. The list updates every 5 seconds. A search field appears when there are more than 3 customers. **View Conversations** opens the calls from that phone number.

A customer is saved when they give a phone number during an order. The order is saved when the OTP confirms it, or when the customer cancels it after giving the phone number.

### Training

Everything the agent knows about the shop: the menu, the FAQ, the allergens, and any module staff add. See [training-doc.md](training-doc.md) for the full description.

- **Modules.** Each module has a name, a type and sections in order. The types are **Menu** (a category and its dishes), **Notes** (a topic and its facts) and **Q&A** (a question and its answer).
- **Edit.** Staff add, edit, delete and reorder modules and sections. The agent uses a change from the next question, in every voice model. No restart is needed.
- **Menu modules.** The dish names also go into the agent's instructions, so the agent can name dishes without a search. A new dish is offered from the next call.
- **Test a Question.** Type a question in the customer's words. The desk shows the 3 results the agent gets, best match first, each with its module.
- Delete asks for confirmation.

The model itself does not change. The agent looks up the answer while it talks.

### Flow

The steps the agent asks for, in order. See [training-doc.md](training-doc.md) for the full description.

- **Built-in steps:** Name, Delivery address, Order items, Payment method, Phone number and OTP. Staff can move them and change what the agent asks. They cannot be removed. OTP is always last, because it confirms the order. Phone number can go anywhere before it, for example first.
- **Custom steps:** staff add a step with a name, the question, optional choices and extra instructions. A step can be required or optional. The answer is saved with the order and shows under the order on the Customers page.
- **Rules the tools enforce:** the agent cannot add items until the required steps before Order items are done. It cannot send the OTP until every required step is done. A step with choices accepts only those choices.
- The greeting asks the first step's question.
- **Save Flow** applies the flow from the next call. A call in progress keeps its flow. **What the Agent Follows** shows the instructions the agent gets. **Reset to Default** restores the default flow.

### Settings

- **Voice Model.** Choose **Gemini** (Google Gemini Live in the cloud, the fastest) or **Local** (the model on this Mac through Ollama). The choice is saved and applies to the next session. If Ollama is not running, the switch to Local fails and says so.
- **Voice on Calls.** Staff record their own voice by reading a script, and name it. The desk shows the original accent, and makes accent versions such as Indian, British or American. Staff play each one, preview it the way callers hear it, and choose the one to use on calls. Local and Claude modes use it. Gemini keeps its own voice. See [voice-doc.md](voice-doc.md).

The desk has no login. Run the server only on a trusted network.

## Screen

The web page shows:

- A start and stop control for the microphone.
- The live transcript of the customer and the agent.
- An activity feed with each tool call and its result, for example `search_knowledge` or `add_to_order`.
- Pipeline cards and a latency chart for each turn.

## Out of scope

- Real SMS delivery of the OTP. The OTP is printed to the server log.
- Real payment collection.
- Order status or tracking after confirmation.
- Languages other than English for replies.
