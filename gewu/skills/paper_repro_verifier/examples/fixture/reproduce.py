"""SYNTHETIC example reproduction script. No real model is trained here.

The default batch_size intentionally disagrees with the paper excerpt so the
three-source parameter table has a code_default to reconcile.
"""
import argparse

LEARNING_RATE = 0.001
EPOCHS = 100
N_FOLDS = 5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch_size", default=64, type=int)
    ap.add_argument("--seed", default=2026, type=int)
    args = ap.parse_args()
    print({"lr": LEARNING_RATE, "batch_size": args.batch_size,
           "epochs": EPOCHS, "n_folds": N_FOLDS, "seed": args.seed})


if __name__ == "__main__":
    main()
