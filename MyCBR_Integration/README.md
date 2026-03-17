# MyCBR Integration

This is a separate project. It does not modify the existing generation, verification, or standalone `MyCBR` pages.

## What it does

It implements a real split architecture for UCD case-based reasoning:

- Python side reuses your current code for:
  - SQL case loading
  - normalization and validation
  - reuse and revise
  - local retention
  - myCBR Workbench bundle export
- Java side uses the local `mycbr.jar` SDK for:
  - storing imported cases in a myCBR project model
  - weighted similarity profiles
  - retrieval through the myCBR engine

## New files

- `java/src/mycbr/integration/MyCBRHttpServer.java`
  - standalone HTTP service around the local myCBR SDK
- `python/bridge.py`
  - Python client for the Java service, reusing existing repo logic
- `python/app.py`
  - standalone Streamlit page for the end-to-end CBR cycle
- `scripts/build_server.ps1`
  - compiles the Java service
- `scripts/run_server.ps1`
  - runs the Java service on localhost

## Service API

- `GET /health`
- `GET /cases`
- `POST /cases/import`
- `POST /cases/add`
- `POST /cases/reset`
- `POST /query`

## Similarity profiles

The Java service exposes three myCBR weighted profiles:

- `balanced`
- `structure`
- `text`

These use myCBR string and integer similarity functions over structured UCD features such as:

- system name
- description
- primary domain
- system kind
- primary/secondary actor text
- use-case text
- actor/use-case/relationship counts
- include / extend / generalization presence
- case origin

## Run

Build the Java service:

```powershell
powershell -ExecutionPolicy Bypass -File MyCBR_Integration/scripts/build_server.ps1
```

Run the Java service:

```powershell
powershell -ExecutionPolicy Bypass -File MyCBR_Integration/scripts/run_server.ps1
```

Run the Python app:

```powershell
streamlit run MyCBR_Integration/python/app.py
```
