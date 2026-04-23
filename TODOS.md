# Project TODOs

## Sales & Store Phase 2
- **What:** Integrate Print-on-Demand (POD) service APIs (e.g., Fine Art America, Printful).
- **Why:** Automate pricing and fulfillment to scale the store beyond manual inquiries.
- **Pros:** Scalability, real-time pricing, reduced manual work.
- **Cons:** High complexity, requires API credentials, potentially high development cost.
- **Context:** Currently, we have a manual order inquiry form. This TODO tracks the move to a fully automated storefront.
- **Depends on:** Successful validation of demand via the manual form.

## Admin Dashboard Enhancements
- **What:** Create an admin view for `data/orders.jsonl`.
- **Why:** To review and manage order inquiries directly in the browser instead of reading the file.
- **Pros:** Better workflow for the artist, ability to mark orders as "contacted" or "completed".
- **Cons:** Requires new admin routes and templates.
- **Context:** As order volume grows, manual file management will become difficult.
