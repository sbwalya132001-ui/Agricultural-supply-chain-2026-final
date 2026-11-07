"""
Rolling-origin back-test of the national forecast.

Each method is asked to forecast the same number of seasons ahead as the real
forecast (e.g. 2024/2025 -> 2026/2027 is 2 steps) from a series cut off at
earlier points in time, and its average absolute percentage miss (MAPE) is
recorded. The ARIMA variant the app uses is chosen on the VALIDATION origins;
the TEST origins (the most recent ones) are only used to report its error, so
the reported error is not flattered by the choice.
"""
import hashlib
import itertools
import warnings

import numpy as np
from statsmodels.tsa.arima.model import ARIMA


# Bump when the methods below change, so stored back-tests are recomputed.
METHOD_VERSION = 2
VALIDATION_ORIGINS = 6
TEST_ORIGINS = 6
# Shortest training series a back-test fold may use.
MIN_TRAINING_SEASONS = 10
AUTO_ORDERS = [(p, 1, q) for p, q in itertools.product(range(2), range(2))]
AUTO_TRENDS = ('n', 't')  # without / with drift


def fixed_arima(values, steps):
    """The project's original model: ARIMA(1,1,1) on the raw values."""
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')  # statsmodels is noisy on short series
        fitted = ARIMA(values, order=(1, 1, 1)).fit()
    return float(fitted.forecast(steps=steps)[-1]), 'ARIMA(1,1,1)'


def auto_log_arima(values, steps):
    """
    ARIMA on log values, order and drift chosen by AIC.

    National input use grows and falls in percentages (policy changes,
    droughts), which the log scale models better than raw tonnes.
    """
    logs = np.log(values)
    best = None
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        for order, trend in itertools.product(AUTO_ORDERS, AUTO_TRENDS):
            try:
                fitted = ARIMA(logs, order=order, trend=trend).fit()
            except (ValueError, np.linalg.LinAlgError):
                continue
            if best is None or fitted.aic < best[0]:
                best = (fitted.aic, order, trend, fitted)
    _, (p, d, q), trend, fitted = best
    label = f'log-ARIMA({p},{d},{q}){"+drift" if trend == "t" else ""}'
    return float(np.exp(fitted.forecast(steps=steps)[-1])), label


def naive(values, steps):
    """Benchmark: the latest season repeats."""
    return float(values[-1]), 'Naive'


def drift(values, steps):
    """Benchmark: the latest season plus the series' average change per season."""
    slope = (values[-1] - values[0]) / (len(values) - 1)
    return float(values[-1] + steps * slope), 'Drift'


CANDIDATES = {'fixed': fixed_arima, 'auto': auto_log_arima}
BENCHMARKS = {'naive': naive, 'drift': drift}


def can_backtest(length, steps):
    return length - steps + 1 - VALIDATION_ORIGINS - TEST_ORIGINS >= MIN_TRAINING_SEASONS


def _origin_ends(length, steps, first_back, count):
    """Training-series lengths for `count` origins, the oldest `first_back` origins before the end."""
    last_end = length - steps + 1
    return [last_end - back for back in range(first_back, first_back - count, -1)]


def _mape(values, steps, method, ends):
    errors = []
    for end in ends:
        prediction, _ = method(values[:end], steps)
        actual = values[end + steps - 1]
        errors.append(abs(prediction - actual) / actual)
    return float(np.mean(errors)) * 100


def fingerprint(seasons, values, steps):
    text = f'{METHOD_VERSION}|{steps}|' + ','.join(f'{s}={v}' for s, v in zip(seasons, values))
    return hashlib.sha256(text.encode()).hexdigest()


def evaluate(seasons, values, steps):
    """Choose the ARIMA variant on the validation origins and score every method on the test origins."""
    values = np.asarray(values, dtype=float)
    validation_ends = _origin_ends(len(values), steps, VALIDATION_ORIGINS + TEST_ORIGINS, VALIDATION_ORIGINS)
    test_ends = _origin_ends(len(values), steps, TEST_ORIGINS, TEST_ORIGINS)
    validation = {name: _mape(values, steps, method, validation_ends) for name, method in CANDIDATES.items()}
    chosen = min(validation, key=validation.get)
    test = {
        name: _mape(values, steps, method, test_ends)
        for name, method in {**CANDIDATES, **BENCHMARKS}.items()
    }
    return {
        'chosen_method': chosen,
        'validation_mape': validation,
        'test_mape': test,
        'first_test_season': seasons[test_ends[0] + steps - 1],
        'last_test_season': seasons[test_ends[-1] + steps - 1],
    }
