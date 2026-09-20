# BillProof 

Turns a hospital bill into a citation-backed comparison against the hospital's own
publicly disclosed prices, plus a negotiation packet.

## Run the demo

```bash
./demo.sh
```

Then open <http://localhost:3000/present> on the projector. It shows a QR code
phones can scan, the address to type, and whether the backend is up and seeded.

- `backend/README.md`, API, MCP server, tests
- `frontend/README.md`, demo-day setup, making the QR code reachable off-laptop
- `DEPLOY.md`, putting it on a custom domain for a live demo
- `docs/`, product truth, data contract, matching and scoring, API/MCP contract
