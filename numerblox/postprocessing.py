# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/05_postprocessing.ipynb (unless otherwise specified).

__all__ = ['BasePostProcessor', 'Standardizer', 'MeanEnsembler', 'DonateWeightedEnsembler', 'GeometricMeanEnsembler',
           'FeatureNeutralizer', 'FeaturePenalizer', 'AwesomePostProcessor']

# Cell
import scipy
import numpy as np
import pandas as pd
import tensorflow as tf
import scipy.stats as sp
from tqdm.auto import tqdm
from typeguard import typechecked
from rich import print as rich_print
from scipy.stats.mstats import gmean
from sklearn.preprocessing import MinMaxScaler

from .numerframe import NumerFrame, create_numerframe
from .preprocessing import BaseProcessor, display_processor_info

# Cell
class BasePostProcessor(BaseProcessor):
    """
    Base class for postprocessing objects.

    Postprocessors manipulate or introduce new prediction columns in a NumerFrame.
    """

    def __init__(self, final_col_name: str):
        super().__init__()
        self.final_col_name = final_col_name
        assert final_col_name.startswith(
            "prediction"
        ), f"final_col name should start with 'prediction'. Got {final_col_name}"

    def transform(self, dataf: NumerFrame, *args, **kwargs) -> NumerFrame:
        ...

# Cell
@typechecked
class Standardizer(BasePostProcessor):
    """
    Uniform standardization of prediction columns.
    All values should only contain values in the range [0...1].

    :param cols: All prediction columns that should be standardized. Use all prediction columns by default.
    """

    def __init__(self, cols: list = None):
        super().__init__(final_col_name="prediction")
        self.cols = cols

    @display_processor_info
    def transform(self, dataf: NumerFrame) -> NumerFrame:
        cols = dataf.prediction_cols if not self.cols else self.cols
        dataf.loc[:, cols] = dataf.groupby(dataf.meta.era_col)[cols].rank(pct=True)
        return NumerFrame(dataf)

# Cell
@typechecked
class MeanEnsembler(BasePostProcessor):
    """
    Take simple mean of multiple cols and store in new col.

    :param final_col_name: Name of new averaged column.
    final_col_name should start with "prediction". \n
    :param cols: Column names to average. \n
    :param standardize: Whether to standardize by era before averaging. Highly recommended as columns that are averaged may have different distributions.
    """

    def __init__(
        self, final_col_name: str, cols: list = None, standardize: bool = False
    ):
        self.cols = cols
        self.standardize = standardize
        super().__init__(final_col_name=final_col_name)

    @display_processor_info
    def transform(self, dataf: NumerFrame) -> NumerFrame:
        cols = self.cols if self.cols else dataf.prediction_cols
        if self.standardize:
            to_average = dataf.groupby(dataf.meta.era_col)[cols].rank(pct=True)
        else:
            to_average = dataf[cols]
        dataf.loc[:, self.final_col_name] = to_average.mean(axis=1)
        rich_print(
            f":stew: Ensembled [blue]'{cols}'[blue] with simple mean and saved in [bold]'{self.final_col_name}'[bold] :stew:"
        )
        return NumerFrame(dataf)

# Cell
@typechecked
class DonateWeightedEnsembler(BasePostProcessor):
    """
    Weighted average as per Donate et al.'s formula
    Paper Link: https://doi.org/10.1016/j.neucom.2012.02.053
    Code source: https://www.kaggle.com/gogo827jz/jane-street-supervised-autoencoder-mlp

    Weightings for 5 folds: [0.0625, 0.0625, 0.125, 0.25, 0.5]

    :param cols: Prediction columns to ensemble.
    Uses all prediction columns by default. \n
    :param final_col_name: New column name for ensembled values.
    """
    def __init__(self, final_col_name: str, cols: list = None):
        super().__init__(final_col_name=final_col_name)
        self.cols = cols
        self.n_cols = len(cols)
        self.weights = self._get_weights()

    @display_processor_info
    def transform(self, dataf: NumerFrame) -> NumerFrame:
        cols = self.cols if self.cols else dataf.prediction_cols
        dataf.loc[:, self.final_col_name] = np.average(
            dataf.loc[:, cols], weights=self.weights, axis=1
        )
        rich_print(
            f":stew: Ensembled [blue]'{cols}'[/blue] with [bold]{self.__class__.__name__}[/bold] and saved in [bold]'{self.final_col_name}'[bold] :stew:"
        )
        return NumerFrame(dataf)

    def _get_weights(self) -> list:
        """Exponential weights."""
        weights = []
        for j in range(1, self.n_cols + 1):
            j = 2 if j == 1 else j
            weights.append(1 / (2 ** (self.n_cols + 1 - j)))
        return weights

# Cell
@typechecked
class GeometricMeanEnsembler(BasePostProcessor):
    """
    Calculate the weighted Geometric mean.

    :param cols: Prediction columns to ensemble.
    Uses all prediction columns by default. \n
    :param final_col_name: New column name for ensembled values.
    """

    def __init__(self, final_col_name: str, cols: list = None):
        super().__init__(final_col_name=final_col_name)
        self.cols = cols

    @display_processor_info
    def transform(self, dataf: NumerFrame, *args, **kwargs) -> NumerFrame:
        cols = self.cols if self.cols else dataf.prediction_cols
        new_col = dataf.loc[:, cols].apply(gmean, axis=1)
        dataf.loc[:, self.final_col_name] = new_col
        rich_print(
            f":stew: Ensembled [blue]'{cols}'[/blue] with [bold]{self.__class__.__name__}[/bold] and saved in [bold]'{self.final_col_name}'[bold] :stew:"
        )
        return NumerFrame(dataf)

# Cell
@typechecked
class FeatureNeutralizer(BasePostProcessor):
    """
    Classic feature neutralization by subtracting linear model.

    :param feature_names: List of column names to neutralize against. Uses all feature columns by default. \n
    :param pred_name: Prediction column to neutralize. \n
    :param proportion: Number in range [0...1] indicating how much to neutralize. \n
    :param suffix: Optional suffix that is added to new column name. \n
    :param cuda: Do neutralization on the GPU \n
    Make sure you have CuPy installed when setting cuda to True. \n
    Installation docs: docs.cupy.dev/en/stable/install.html
    """
    def __init__(
        self,
        feature_names: list = None,
        pred_name: str = "prediction",
        proportion: float = 0.5,
        suffix: str = None,
        cuda = False
    ):
        self.pred_name = pred_name
        self.proportion = proportion
        assert (
            0.0 <= proportion <= 1.0
        ), f"'proportion' should be a float in range [0...1]. Got '{proportion}'."
        self.new_col_name = (
            f"{self.pred_name}_neutralized_{self.proportion}_{suffix}"
            if suffix
            else f"{self.pred_name}_neutralized_{self.proportion}"
        )
        super().__init__(final_col_name=self.new_col_name)

        self.feature_names = feature_names
        self.cuda = cuda

    @display_processor_info
    def transform(self, dataf: NumerFrame) -> NumerFrame:
        feature_names = self.feature_names if self.feature_names else dataf.feature_cols
        neutralized_preds = dataf.groupby(dataf.meta.era_col).apply(
            lambda x: self.normalize_and_neutralize(x, [self.pred_name], feature_names)
        )
        dataf.loc[:, self.new_col_name] = MinMaxScaler().fit_transform(
            neutralized_preds
        )
        rich_print(
            f":robot: Neutralized [bold blue]'{self.pred_name}'[bold blue] with proportion [bold]'{self.proportion}'[/bold] :robot:"
        )
        rich_print(
            f"New neutralized column = [bold green]'{self.new_col_name}'[/bold green]."
        )
        return NumerFrame(dataf)

    def neutralize(self, dataf: pd.DataFrame, columns: list, by: list) -> pd.DataFrame:
        """ Neutralize on CPU. """
        scores = dataf[columns]
        exposures = dataf[by].values
        scores = scores - self.proportion * exposures.dot(
            np.linalg.pinv(exposures).dot(scores)
        )
        return scores / scores.std()

    def neutralize_cuda(self, dataf: pd.DataFrame, columns: list, by: list) -> np.ndarray:
        """ Neutralize on GPU. """
        try:
            import cupy
        except ImportError:
            raise ImportError("CuPy not installed. Set cuda=False or install CuPy. Installation docs: docs.cupy.dev/en/stable/install.html")
        scores = cupy.array(dataf[columns].values)
        exposures = cupy.array(dataf[by].values)
        scores = scores - self.proportion * exposures.dot(
            cupy.linalg.pinv(exposures).dot(scores)
        )
        return cupy.asnumpy(scores / scores.std())

    @staticmethod
    def normalize(dataf: pd.DataFrame) -> np.ndarray:
        normalized_ranks = (dataf.rank(method="first") - 0.5) / len(dataf)
        return sp.norm.ppf(normalized_ranks)

    def normalize_and_neutralize(
        self, dataf: pd.DataFrame, columns: list, by: list
    ) -> pd.DataFrame:
        dataf[columns] = self.normalize(dataf[columns])
        neutralization_func = self.neutralize if not self.cuda else self.neutralize_cuda
        dataf[columns] = neutralization_func(dataf, columns, by)
        return dataf[columns]

# Cell
@typechecked
class FeaturePenalizer(BasePostProcessor):
    """
    Feature penalization with TensorFlow.

    Source (by jrb): https://github.com/jonrtaylor/twitch/blob/master/FE_Clipping_Script.ipynb

    Source of first PyTorch implementation (by Michael Oliver / mdo): https://forum.numer.ai/t/model-diagnostics-feature-exposure/899/12

    :param feature_names: List of column names to reduce feature exposure. Uses all feature columns by default. \n
    :param pred_name: Prediction column to neutralize. \n
    :param max_exposure: Number in range [0...1] indicating how much to reduce max feature exposure to.
    """
    def __init__(
        self,
        max_exposure: float,
        feature_names: list = None,
        pred_name: str = "prediction",
        suffix: str = None,
    ):
        self.pred_name = pred_name
        self.max_exposure = max_exposure
        assert (
            0.0 <= max_exposure <= 1.0
        ), f"'max_exposure' should be a float in range [0...1]. Got '{max_exposure}'."
        self.new_col_name = (
            f"{self.pred_name}_penalized_{self.max_exposure}_{suffix}"
            if suffix
            else f"{self.pred_name}_penalized_{self.max_exposure}"
        )
        super().__init__(final_col_name=self.new_col_name)

        self.feature_names = feature_names

    @display_processor_info
    def transform(self, dataf: NumerFrame) -> NumerFrame:
        feature_names = (
            dataf.feature_cols if not self.feature_names else self.feature_names
        )
        penalized_data = self.reduce_all_exposures(
            dataf=dataf, column=self.pred_name, neutralizers=feature_names
        )
        dataf.loc[:, self.new_col_name] = penalized_data[self.pred_name]
        return NumerFrame(dataf)

    def reduce_all_exposures(
        self,
        dataf: NumerFrame,
        column: str = "prediction",
        neutralizers: list = None,
        normalize=True,
        gaussianize=True,
    ) -> pd.DataFrame:
        if neutralizers is None:
            neutralizers = [x for x in dataf.columns if x.startswith("feature")]
        neutralized = []

        for era in tqdm(dataf[dataf.meta.era_col].unique()):
            dataf_era = dataf[dataf[dataf.meta.era_col] == era]
            scores = dataf_era[[column]].values
            exposure_values = dataf_era[neutralizers].values

            if normalize:
                scores2 = []
                for x in scores.T:
                    x = (scipy.stats.rankdata(x, method="ordinal") - 0.5) / len(x)
                    if gaussianize:
                        x = scipy.stats.norm.ppf(x)
                    scores2.append(x)
                scores = np.array(scores2)[0]

            scores, weights = self._reduce_exposure(
                scores, exposure_values, len(neutralizers), None
            )

            scores /= tf.math.reduce_std(scores)
            scores -= tf.reduce_min(scores)
            scores /= tf.reduce_max(scores)
            neutralized.append(scores.numpy())

        predictions = pd.DataFrame(
            np.concatenate(neutralized), columns=[column], index=dataf.index
        )
        return predictions

    def _reduce_exposure(self, prediction, features, input_size=50, weights=None):
        model = tf.keras.models.Sequential(
            [
                tf.keras.layers.Input(input_size),
                tf.keras.experimental.LinearModel(use_bias=False),
            ]
        )
        feats = tf.convert_to_tensor(features - 0.5, dtype=tf.float32)
        pred = tf.convert_to_tensor(prediction, dtype=tf.float32)
        if weights is None:
            optimizer = tf.keras.optimizers.Adamax()
            start_exp = self.__exposures(feats, pred[:, None])
            target_exps = tf.clip_by_value(
                start_exp, -self.max_exposure, self.max_exposure
            )
            self._train_loop(model, optimizer, feats, pred, target_exps)
        else:
            model.set_weights(weights)
        return pred[:, None] - model(feats), model.get_weights()

    def _train_loop(self, model, optimizer, feats, pred, target_exps):
        for i in range(1000000):
            loss, grads = self.__train_loop_body(model, feats, pred, target_exps)
            optimizer.apply_gradients(zip(grads, model.trainable_variables))
            if loss < 1e-7:
                break

    @tf.function(experimental_relax_shapes=True)
    def __train_loop_body(self, model, feats, pred, target_exps):
        with tf.GradientTape() as tape:
            exps = self.__exposures(feats, pred[:, None] - model(feats, training=True))
            loss = tf.reduce_sum(
                tf.nn.relu(tf.nn.relu(exps) - tf.nn.relu(target_exps))
                + tf.nn.relu(tf.nn.relu(-exps) - tf.nn.relu(-target_exps))
            )
        return loss, tape.gradient(loss, model.trainable_variables)

    @staticmethod
    @tf.function(experimental_relax_shapes=True, experimental_compile=True)
    def __exposures(x, y):
        x = x - tf.math.reduce_mean(x, axis=0)
        x = x / tf.norm(x, axis=0)
        y = y - tf.math.reduce_mean(y, axis=0)
        y = y / tf.norm(y, axis=0)
        return tf.matmul(x, y, transpose_a=True)

# Cell
@typechecked
class AwesomePostProcessor(BasePostProcessor):
    """
    TEMPLATE - Do some awesome postprocessing.

    :param final_col_name: Column name to store manipulated or ensembled predictions in.
    """

    def __init__(self, final_col_name: str, *args, **kwargs):
        super().__init__(final_col_name=final_col_name)

    @display_processor_info
    def transform(self, dataf: NumerFrame, *args, **kwargs) -> NumerFrame:
        # Do processing
        ...
        # Add new column(s) for manipulated data
        dataf.loc[:, self.final_col_name] = ...
        ...
        # Parse all contents to the next pipeline step
        return NumerFrame(dataf)