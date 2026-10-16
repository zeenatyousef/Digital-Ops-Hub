import multiprocessing
import importlib
import uvicorn
import sys
import os
import time

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def run_vishaqa():
    app = importlib.import_module("apps.vishaqa-service.main").app
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info")

def run_asma():
    app = importlib.import_module("apps.asma-service.main").app
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="info")

def run_esha():
    app = importlib.import_module("apps.esha-service.main").app
    uvicorn.run(app, host="127.0.0.1", port=8003, log_level="info")

def run_gateway():
    app = importlib.import_module("apps.core_gateway.main").app
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    print("Starting all microservices concurrently...")
    
    p_vishaqa = multiprocessing.Process(target=run_vishaqa, name="Vishaqa-8001")
    p_asma = multiprocessing.Process(target=run_asma, name="Asma-8002")
    p_esha = multiprocessing.Process(target=run_esha, name="Esha-8003")
    p_gateway = multiprocessing.Process(target=run_gateway, name="CoreGateway-8000")

    p_vishaqa.start()
    time.sleep(1)
    p_asma.start()
    time.sleep(1)
    p_esha.start()
    time.sleep(1)
    p_gateway.start()

    print("All 4 services launched:")
    print(" - Vishaqa: http://127.0.0.1:8001")
    print(" - Asma:    http://127.0.0.1:8002")
    print(" - Esha:    http://127.0.0.1:8003")
    print(" - Gateway: http://127.0.0.1:8000")

    try:
        p_vishaqa.join()
        p_asma.join()
        p_esha.join()
        p_gateway.join()
    except KeyboardInterrupt:
        print("Terminating services...")
        p_vishaqa.terminate()
        p_asma.terminate()
        p_esha.terminate()
        p_gateway.terminate()
