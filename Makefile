.PHONY: install demo test backend ui compose clean

# Run the offline end-to-end demo over all ground-truth cases (no LLM needed).
demo:
	LLM_MODE=mock python run_demo.py

# Run the unit tests.
test:
	python -m pytest test_conformance.py -v || python -m pytest test_conformance.py

# Install dependencies.
install:
	pip install -r requirements.txt

# Start the FastAPI backend (mock LLM mode).
backend:
	LLM_MODE=mock uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Start the Streamlit UI (point it at the backend).
ui:
	DRIFTGUARDIAN_API=http://localhost:8000 streamlit run app.py

# Start both via docker compose.
compose:
	docker compose up --build

clean:
	rm -rf __pycache__ .pytest_cache data/outputs/*.json
