import pandas as pd
from pathlib import Path


# Find project folder
BASE_DIR = Path(__file__).resolve().parent.parent

# Load training data
file_path = BASE_DIR / "data" / "training_data.csv"

data = pd.read_csv(file_path)

print("Training dataset loaded successfully.")
print("\nDataset shape:")
print(data.shape)

print("\nFirst 5 rows:")
print(data.head())

print("\nClass distribution:")
print(data["Emergency"].value_counts())