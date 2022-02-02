# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/07_evaluation.ipynb (unless otherwise specified).

__all__ = ['BaseEvaluator', 'NumeraiClassicEvaluator', 'NumeraiSignalsEvaluator']

# Cell
import numpy as np
import pandas as pd
from tqdm.auto import tqdm
from typing import Tuple, Union

from .numerframe import NumerFrame, create_numerframe
from .postprocessing import FeatureNeutralizer

# Cell
class BaseEvaluator:
    """
    Evaluation functionality that holds for both
    Numerai Classic and Numerai Signals.
    :param era_col: Column name pointing to eras.
    Most commonly "era" for Classic and "friday_date" for Signals.
    :param fast_mode: Will skip compute intensive metrics, namely
    max_exposure, feature neutral mean and TB200, if set to True.
    """
    def __init__(self, era_col: str = "era", fast_mode = False):
        self.era_col = era_col
        self.fast_mode = fast_mode

    def full_evaluation(self,
                        dataf: NumerFrame,
                        example_col: str,
                        pred_cols: list = None,
                        target_col: str = "target"
                        ) -> pd.DataFrame:
        """
        Perform evaluation for each prediction column in the Dataset
        against give target and example prediction column.
        """
        val_stats = pd.DataFrame()
        dataf.dataf = dataf.fillna(0.5)
        pred_cols = dataf.prediction_cols if not pred_cols else pred_cols
        for col in tqdm(pred_cols, desc="Evaluation: "):
            col_stats = self.evaluation_one_col(dataf=dataf, pred_col=col,
                                                target_col=target_col,
                                                example_col=example_col)
            val_stats = pd.concat([val_stats, col_stats], axis=0)
        return val_stats

    def evaluation_one_col(self, dataf: Union[pd.DataFrame, NumerFrame], pred_col: str, target_col: str, example_col: str):
        """
        Perform evaluation for one prediction column
        against given target and example prediction column.
        """
        col_stats = pd.DataFrame()
        # Compute stats
        val_corrs = self.per_era_corrs(dataf=dataf,
                                        pred_col=pred_col,
                                        target_col=target_col
                                       )
        mean, std, sharpe = self.mean_std_sharpe(era_corrs=val_corrs)
        max_drawdown = self.max_drawdown(era_corrs=val_corrs)
        apy = self.apy(era_corrs=val_corrs)
        example_corr = self.example_correlation(dataf=dataf,
                                                pred_col=pred_col,
                                                example_col=example_col
                                                )
        mmc_mean, mmc_std, mmc_sharpe = self.mmc(dataf=dataf,
                                                 pred_col=pred_col,
                                                 target_col=target_col,
                                                 example_col=example_col
                                                 )

        col_stats.loc[pred_col, "target"] = target_col
        col_stats.loc[pred_col, "mean"] = mean
        col_stats.loc[pred_col, "std"] = std
        col_stats.loc[pred_col, "sharpe"] = sharpe
        col_stats.loc[pred_col, "max_drawdown"] = max_drawdown
        col_stats.loc[pred_col, "apy"] = apy
        col_stats.loc[pred_col, "mmc_mean"] = mmc_mean
        col_stats.loc[pred_col, "mmc_std"] = mmc_std
        col_stats.loc[pred_col, "mmc_sharpe"] = mmc_sharpe
        col_stats.loc[pred_col, "corr_with_example_preds"] = example_corr

        # Compute intensive stats
        if not self.fast_mode:
            max_feature_exposure = self.max_feature_exposure(dataf=dataf, pred_col=pred_col)
            fn_mean = self.feature_neutral_mean(dataf=dataf, pred_col=pred_col)
            tb200_mean, tb200_std, tb200_sharpe = self.tbx_mean_std_sharpe(dataf=dataf,
                                                                           pred_col=pred_col,
                                                                           target_col=target_col,
                                                                           tb=200
                                                                           )
            col_stats.loc[pred_col, "max_feature_exposure"] = max_feature_exposure
            col_stats.loc[pred_col, "feature_neutral_mean"] = fn_mean
            col_stats.loc[pred_col, "tb200_mean"] = tb200_mean
            col_stats.loc[pred_col, "tb200_std"] = tb200_std
            col_stats.loc[pred_col, "tb200_sharpe"] = tb200_sharpe
        return col_stats

    def per_era_corrs(self, dataf: pd.DataFrame, pred_col: str,
                      target_col: str) -> pd.Series:
        """ Correlation between prediction and target for each era. """
        return dataf.groupby(dataf[self.era_col])\
            .apply(lambda d: self._normalize_uniform(d[pred_col].fillna(0.5))
                   .corr(d[target_col]))

    def mean_std_sharpe(self, era_corrs: pd.Series) -> Tuple[np.float64, np.float64, np.float64]:
        """
        Average, standard deviation and Sharpe ratio for
        correlations per era.
        """
        mean = pd.Series(era_corrs.mean()).item()
        std = pd.Series(era_corrs.std(ddof=0)).item()
        sharpe = mean / std
        return mean, std, sharpe

    @staticmethod
    def max_drawdown(era_corrs: pd.Series) -> np.float64:
        """ Maximum drawdown per era. """
        # Arbitrarily large window
        rolling_max = (era_corrs + 1).cumprod().rolling(window=9000,
                                                        min_periods=1).max()
        daily_value = (era_corrs + 1).cumprod()
        max_drawdown = -((rolling_max - daily_value) / rolling_max).max()
        return max_drawdown

    @staticmethod
    def apy(era_corrs: pd.Series) -> np.float64:
        """ Annual percentage yield. """
        payout_scores = era_corrs.clip(-0.25, 0.25)
        payout_daily_value = (payout_scores + 1).cumprod()
        apy = (
                      (
                              (payout_daily_value.dropna().iloc[-1])
                              ** (1 / len(payout_scores))
                      )
                      ** 49  # 52 weeks of compounding minus 3 for stake compounding lag
                      - 1
              ) * 100
        return apy

    def example_correlation(self, dataf: Union[pd.DataFrame, NumerFrame],
                            pred_col: str, example_col: str):
        """ Correlations with example predictions. """
        return self.per_era_corrs(dataf=dataf,
                                  pred_col=pred_col,
                                  target_col=example_col,
                                  ).mean()

    def max_feature_exposure(self, dataf: Union[pd.DataFrame, NumerFrame], pred_col: str) -> np.float64:
        """ Maximum exposure over all features. """
        max_per_era = dataf.groupby(self.era_col).apply(
            lambda d: d[dataf.feature_cols].corrwith(d[pred_col]).abs().max())
        max_feature_exposure = max_per_era.mean()
        return max_feature_exposure

    def feature_neutral_mean(self, dataf: Union[pd.DataFrame, NumerFrame], pred_col: str) -> np.float64:
        """ Feature neutralized mean performance. """
        fn = FeatureNeutralizer(pred_name=pred_col,
                                era_col=self.era_col,
                                proportion=1.0)
        neutralized_dataf = fn(dataf=dataf)
        return neutralized_dataf[fn.final_col_name].mean()

    def tbx_mean_std_sharpe(self,
                            dataf: pd.DataFrame,
                            pred_col: str,
                            target_col: str,
                            tb: int = 200
                            ) -> Tuple[np.float64, np.float64, np.float64]:
        """
        Calculate Mean, Standard deviation and Sharpe ratio
        when we focus on the x top and x bottom predictions.
        :param tb: How many of top and bottom predictions to focus on.
        TB200 is the most common situation.
        """
        tb_val_corrs = self._score_by_date(dataf=dataf,
                                           columns=[pred_col],
                                           target=target_col,
                                           tb=tb)
        return self.mean_std_sharpe(era_corrs=tb_val_corrs)

    def mmc(self, dataf: pd.DataFrame,
            pred_col: str,
            target_col: str,
            example_col: str
            ) -> Tuple[np.float64, np.float64, np.float64]:
        """ MMC Mean, standard deviation and Sharpe ratio. """
        mmc_scores = []
        corr_scores = []
        for _, x in dataf.groupby(self.era_col):
            series = self.neutralize_series(self._normalize_uniform(x[pred_col]), (x[example_col]))
            mmc_scores.append(np.cov(series, x[target_col])[0, 1] / (0.29 ** 2))
            corr_scores.append(self._normalize_uniform(x[pred_col]).corr(x[target_col]))

        val_mmc_mean = np.mean(mmc_scores)
        val_mmc_std = np.std(mmc_scores)
        corr_plus_mmcs = [c + m for c, m in zip(corr_scores, mmc_scores)]
        corr_plus_mmc_sharpe = np.mean(corr_plus_mmcs) / np.std(corr_plus_mmcs)
        return val_mmc_mean, val_mmc_std, corr_plus_mmc_sharpe

    @staticmethod
    def neutralize_series(series, by, proportion=1.0):
        scores = series.values.reshape(-1, 1)
        exposures = by.values.reshape(-1, 1)

        # this line makes series neutral to a constant column so that it's centered and for sure gets corr 0 with exposures
        exposures = np.hstack(
            (exposures,
             np.array([np.mean(series)] * len(exposures)).reshape(-1, 1)))

        correction = proportion * (exposures.dot(
            np.linalg.lstsq(exposures, scores, rcond=None)[0]))
        corrected_scores = scores - correction
        neutralized = pd.Series(corrected_scores.ravel(), index=series.index)
        return neutralized

    def _score_by_date(self, dataf: pd.DataFrame, columns: list, target: str, tb: int = None):
        """
        Get era correlation based on given tb (x top and bottom predictions).
        :param tb: How many of top and bottom predictions to focus on.
        TB200 is the most common situation.
        """
        unique_eras = dataf[self.era_col].unique()
        computed = []
        for u in unique_eras:
            df_era = dataf[dataf[self.era_col] == u]
            era_pred = np.float64(df_era[columns].values.T)
            era_target = np.float64(df_era[target].values.T)

            if tb is None:
                ccs = np.corrcoef(era_target, era_pred)[0, 1:]
            else:
                tbidx = np.argsort(era_pred, axis=1)
                tbidx = np.concatenate([tbidx[:, :tb], tbidx[:, -tb:]], axis=1)
                ccs = [np.corrcoef(era_target[idx], pred[idx])[0, 1] for idx, pred in zip(tbidx, era_pred)]
                ccs = np.array(ccs)
            computed.append(ccs)
        return pd.DataFrame(np.array(computed), columns=columns, index=dataf[self.era_col].unique())

    @staticmethod
    def _normalize_uniform(df: pd.DataFrame) -> pd.Series:
        """ Normalize predictions uniformly using ranks. """
        x = (df.rank(method="first") - 0.5) / len(df)
        return pd.Series(x, index=df.index)


# Cell
class NumeraiClassicEvaluator(BaseEvaluator):
    def __init__(self, era_col: str = "era", fast_mode = False):
        super().__init__(era_col=era_col, fast_mode=fast_mode)

# Cell
class NumeraiSignalsEvaluator(BaseEvaluator):
    def __init__(self, era_col: str = "era", fast_mode = False):
        super().__init__(era_col=era_col, fast_mode=fast_mode)