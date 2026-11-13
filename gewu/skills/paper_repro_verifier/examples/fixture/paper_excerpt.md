# Example Paper Excerpt (SYNTHETIC — NOT A REAL PAPER)

All numbers below are invented for interface testing. Do not cite them as results.

## 3. Methods

We set the learning rate to 0.001 and the batch size to 32. The number of
epochs = 100 and folds = 5. Weight decay: 0.0005. The random seed is 2026.
All experiments used Python 3.11 and numpy 1.26.4.

## 4. Results

Table 1. Main comparison on the example task (kcal/kg):

| method | RMSE | R2 |
|---|---|---|
| baseline | 0.2500 | 0.7000 |
| proposed | 0.1234 | 0.8888 |

The proposed method achieves RMSE 0.1234 ± 0.0100 across five folds.
MAE was not reported. The evaluation script is not released.

## 5. Limitations

The dataset requires an application and is not publicly available.
