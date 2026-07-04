# digiPrint — Product Overview

**Audience:** all readers (written for stakeholders; no technical background needed).

## What it is

digiPrint is digiDirect's internal operations platform for the **film processing lab business** across five retail stores — Bondi, Miranda, Parramatta, Brisbane and Cannington. It replaces the previous spreadsheet-and-scripts workflow with one system that tracks every roll of film from the moment a customer pays until their scans land in their inbox.

## The problem it solves

Film processing involves a physical chain (film → development → scanning → delivery) spread across sales staff, lab technicians, and automated tools. Before digiPrint, that chain was stitched together with Google Sheets, manual folder moves, and hand-written emails — easy to drop a roll, double-book a twin-check ticket, or forget to notify a customer.

## What it does

- **Captures every sale automatically.** Sales made in Pronto (the POS) flow into digiPrint within ~10 minutes as "inbound" orders — before the film even reaches the lab bench, the system knows it's coming.
- **Books film in fast.** The Intake screen is a keyboard-first flow: scan the receipt number, confirm the customer details it already knows, type the twin-check ticket numbers (single or ranges like `0042-0051`), done. Duplicate ticket numbers are blocked per store.
- **Tracks the pipeline.** Every order moves through `inbound → booked in → scanning → delivered`, with timestamps and a full audit trail of who did what.
- **Automates delivery.** When the scanner uploads a roll's images to Google Drive, digiPrint matches the folder to the right order, files it neatly (`Delivered/2026/7/<order> <customer>`), makes it shareable, and — once every roll is done — emails the customer their link automatically. Orders only count as delivered once that email actually sends.
- **Handles the edge cases.** Blank rolls (with a tactful customer notification), rescans, twin-number mix-up corrections, manual bookings when Pronto is down, storage-expiry dates in every email, and premium add-ons (border scans with automated image processing, contact sheets, rebate scans) detected straight from the sale's SKUs.
- **Watches the money.** Refunds appearing in Pronto are matched back to orders automatically — a full refund before delivery cancels the order; anything the system can't match confidently is queued for a human to review.
- **Shows the health of the operation.** Per-store dashboards: today's volume, pending and overdue work, blanks, and average turnaround time.

## Who uses it

| User | What they do in digiPrint |
|---|---|
| Retail/lab staff | Book film in, mark blanks, fix twin numbers, send/resend customer emails |
| Store admins | Everything above plus twin resets and forcing data refreshes |
| Head office (master admin) | Cross-store visibility, all stores' dashboards and orders |
| Customers | Don't log in — they receive branded emails with their scan links |

## What it's built on (one paragraph)

A React web app talking to a Python (FastAPI) API, with data in a managed PostgreSQL database (Supabase) and deep integrations into Google Drive (scan delivery), Google Sheets (Pronto data feed) and Gmail (per-store customer emails). Details in `02-architecture.md`.

## Current status (as of July 2026)

Live day-to-day flow works end to end. Recent work added the inbound pipeline, refund matching, and refreshed (v4) email designs that are staged but not yet switched on. Known rough edges are catalogued honestly in each spec's "Known gaps" section — the largest being frontend screens that still show the old status names, and API endpoints that still need authentication added. B2B vendor batch tracking is designed (database tables exist) but not active in the app.
