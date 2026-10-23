# Delivery areas

This document describes how the agent takes the delivery address, and the **Delivery** section of the desk, where staff set the cities, zones and pincodes the shop delivers to.

For the rest of the system, see [architecture.md](architecture.md), [technical-doc.md](technical-doc.md) and [training-doc.md](training-doc.md).

## Summary

- The agent asks for the **door number**, **street** and **pincode**. The customer can give them in one sentence or over several turns.
- The agent checks the pincode against the delivery areas at once. If the shop does not deliver there, the agent says so and asks for another address.
- If the customer names only the area, for example "Koramangala", the agent suggests its pincode and checks it with the customer.
- The saved address has the form `12B, 5th Cross, 4th Block, Koramangala, Bengaluru 560034`.
- **Delivery** (`/desk/#delivery`) lists the cities. A city has zones, and a zone has pincodes. Each pincode has its area names.
- Staff can add, edit and delete cities, zones and pincodes. They can change a pincode, move it to another zone, and switch a pincode, zone or city off.
- A pincode gets delivery only when the pincode, its zone and its city are all on.
- A change applies to the next address the agent checks. No restart is needed.
- All three voice modes (Gemini, Local and Claude) use the same check.

## Where the data comes from

The first start fills the areas from `components/python/knowledge/delivery_areas.json`. The script `components/python/scripts/fetch_pincodes.py` builds this file from **India Post** data:

- Source: [api.postalpincode.in](https://api.postalpincode.in), a free API with no key. It serves the same data as the [All India Pincode Directory](https://www.data.gov.in/catalog/all-india-pincode-directory) on data.gov.in.
- For each pincode the API gives its post offices and its postal division. The script uses the post office names as the area names, and the division as the zone.
- To get the data again: `make fetch-pincodes`.

Bengaluru starts with these zones:

| Zone | Postal division | Pincodes | Delivery |
|------|-----------------|----------|----------|
| Central | Bangalore GPO | 1 | On |
| East | Bangalore East | 37 | On |
| West | Bangalore West | 30 | On |
| North | Bangalore North | 1 | On |
| South | Bangalore South | 39 | On |
| Outskirts | Other (562xxx in Bangalore district: Anekal, Attibele, Sarjapura, Bagalur and others) | 7 | Off |

Outskirts starts off because it is far from the restaurant. Staff can switch it on.

The postal divisions are not the same as the city corporation zones. To use other zones, add them on the desk and move the pincodes to them, or change `ZONES` in the script.

To add another city, add it on the desk. Or add its pincode range to the script, run `make fetch-pincodes`, and choose **Reset to India Post Data** on the desk.

## How to use Delivery

1. Open the desk and choose **Delivery**.
2. To check a pincode or area, type it in **Find a Pincode or Area**. A result that is not found means the agent says the shop does not deliver there.
3. To stop delivery to a zone, switch the zone off. To stop delivery to one pincode, choose **Edit** on the pincode and switch **Deliver to this pincode** off.
4. To change a pincode, choose **Edit**, change the number, the area names or the zone, and choose **Save**.
5. To add a pincode, open the zone and choose **+ Add Pincode**.
6. To add a zone, type its name under the zones and choose **Add Zone**.
7. To add a city, choose **+ Add City**. Enter other names customers use, for example "Mysore" for Mysuru.
8. **Reset to India Post Data** replaces every city, zone and pincode with the seed file. Your changes are lost.

## Technical details

### Data

Three SQLite tables in `store.py`:

| Table | Columns |
|-------|---------|
| `delivery_cities` | `id`, `name`, `aliases` (JSON list), `active`, `position` |
| `delivery_zones` | `id`, `city_id`, `name`, `active`, `position` |
| `delivery_pincodes` | `pincode` (primary key), `zone_id`, `areas` (JSON list), `active` |

A pincode can be in one zone only. `delivery.seed()` fills the tables on the first start and sets the setting `delivery_seeded`.

### The address tool

`orders.save_delivery_address(door_number, street, pincode, area="")`:

- Keeps the parts in `Order.address_parts`, so the model can send the parts the customer said in each turn.
- Checks the pincode as soon as it is given. An unknown or switched-off pincode clears the parts and returns "We don't deliver to …".
- Returns the parts that are still missing. If the pincode is missing and the area or street matches an area name, it adds a suggestion, for example "Koramangala is pincode 560034".
- When all parts are there, saves the address and sets `address_verified`. If the customer did not name the area, it takes the first area name of the pincode.

In the Local mode, the harness takes the pincode from the customer's words (`orders.spoken_pincode`), so "five six double zero three four" becomes `560034`.

The address step tells every model: "Get the door number, street and 6-digit pincode. Call save_delivery_address with the parts they said…". A saved flow that still has the old default question ("What is your delivery address and city?") gets the new default question when it loads. A question that staff changed is kept.

### API

Every call that changes something returns all cities, in the same format as `GET /api/delivery`.

| Route | Body | Result |
|-------|------|--------|
| `GET /api/delivery` | none | All cities with zones and pincodes |
| `POST /api/delivery/cities` | `{"name", "aliases"}` | 201 |
| `PUT /api/delivery/cities/{id}` | `{"name", "aliases", "active"}` | |
| `DELETE /api/delivery/cities/{id}` | none | Deletes its zones and pincodes too |
| `POST /api/delivery/cities/{id}/zones` | `{"name"}` | 201 |
| `PUT /api/delivery/zones/{id}` | `{"name", "active"}` | |
| `DELETE /api/delivery/zones/{id}` | none | Deletes its pincodes too |
| `POST /api/delivery/zones/{id}/pincodes` | `{"pincode", "areas"}` | 201 |
| `PUT /api/delivery/pincodes/{pincode}` | `{"pincode", "areas", "active", "zone_id"}` | Can change the number and the zone |
| `DELETE /api/delivery/pincodes/{pincode}` | none | |
| `POST /api/delivery/reset` | none | Loads the seed file again |

A pincode must have 6 digits and must not start with 0. A pincode that is already in a zone returns 400 with the name of that zone.

### How it was tested

- The API with FastAPI's `TestClient` on a scratch database: seed, add, a bad and a duplicate pincode, change the number and zone, add and delete a city and a zone.
- The tool: parts over three turns, the area suggestion, a pincode in a zone that is off, a pincode in no zone (Mumbai, 400001), and a zone switched off on the desk.
- The Local model (`qwen3.5:4b`), with typed customer turns: the address in three turns, the address in one sentence, and an Outskirts address followed by a good one.
- The desk at 1280, 500 and 375 px wide, in light and dark mode.

The address was not tested in a live voice call.

### Limits

- **The area is not checked against the pincode.** If the customer says "Indiranagar, 560034", the address keeps both.
- **No delivery fee or time per zone.** The FAQ in Training still gives one delivery fee.
- **No login.** Anyone who can reach the server can change the delivery areas, like the rest of `/api`.
- **Python only.** The TypeScript backend does not check addresses.
