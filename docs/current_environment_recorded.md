# Recorded environment — November 9, 2026 review

These values come from saved notebook outputs. They were not verified by installing a new environment during this review, and this file is not a dependency lock or tested installation recipe.

| Component | Recorded version or value |
|---|---|
| Python | 3.12.6 |
| Operating system | Windows 11 |
| ipykernel | 7.4.0 |
| pandas | 3.1.1 |
| NumPy | 2.5.4 |
| Matplotlib | 3.11.2 |
| seaborn | 0.13.2 |
| scikit-learn | 1.9.1 |
| PyYAML | 6.0.3 |
| python-dotenv | 1.2.4 |
| pytest | 9.2.0 |
| PyTorch | 2.14.1+cu126 |
| PyTorch compiled CUDA | 12.6 |
| GPU used by the PyTorch smoke test | NVIDIA GeForce RTX 3080, approximately 10 GiB |
| CPU / system RAM | Intel Core i7-12700, 20 logical cores / approximately 63.7 GiB |
| Ollama | 0.40.15 |
| Local model tag / quantization | llama3.1:8b / Q4_K_M |
| Local model digest | 46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e |

The saved `pip check` output reported no broken requirements. The CUDA wheel source and full transitive dependency set still need to be documented and tested for installation on another machine. Ollama is a separate installation; PyTorch detecting a GPU does not establish Ollama GPU offloading.

The Step 7 request used `/api/generate`, temperature 0, seed 42, context 4096, and output limit 256. The later `/api/chat` integration and larger context are plans, not verified settings in this snapshot.

Next setup work: create the actual dependency specification from the development environment, separate analysis dependencies from optional training/application dependencies, and test the documented setup in a fresh environment before claiming a fresh-clone reproduction.
