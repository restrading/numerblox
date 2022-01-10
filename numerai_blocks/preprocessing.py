# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/03_preprocessing.ipynb (unless otherwise specified).

__all__ = ['BaseProcessor', 'support_dataf_processing', 'support_dataset_processing', 'display_processor_info',
           'CopyPreProcessor', 'GroupStatsPreProcessor']

# Cell
import uuid
import numpy as np
import pandas as pd
import datetime as dt
from functools import wraps
from typeguard import typechecked
from abc import ABC, abstractmethod
from rich import print as rich_print

from .dataset import Dataset

# Cell
@typechecked
class BaseProcessor(ABC):
    """
    New Preprocessors and Postprocessors should inherit from this object
    and implement the transform method.
    """
    def __init__(self):
        ...

    @abstractmethod
    def transform(self, dataset: Dataset, *args, **kwargs) -> Dataset:
        ...

    def __call__(self, dataset: Dataset, *args, **kwargs) -> Dataset:
        return self.transform(dataset=dataset, *args, **kwargs)

# Cell
def support_dataf_processing(func):
    """
    Make Dataset processor compatible with DataFrame input.
    :param func: Some function/method that takes Dataset as input
    and returns Dataset.
    """
    @wraps(func)
    def wrapper(dataf: pd.DataFrame, *args, **kwargs) -> pd.DataFrame:
        return func(Dataset(dataf), *args, **kwargs).dataf
    return wrapper

def support_dataset_processing(func):
    """
    Make existing DataFrame transformer compatible with Dataset input.
    :param func: Some function/method that takes Pandas DataFrame as input
    and return Pandas DataFrame.
    """
    @wraps(func)
    def wrapper(dataset: Dataset, *args, **kwargs) -> Dataset:
        dataf_transform = func(dataset.dataf, *args, **kwargs)
        metadata = dataset.__dict__
        metadata.pop("dataf", None)
        return Dataset(dataf_transform, metadata)
    return wrapper

# Cell
def display_processor_info(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        tic = dt.datetime.now()
        result = func(*args, **kwargs)
        time_taken = str(dt.datetime.now() - tic)
        class_name = func.__qualname__.split('.')[0]
        rich_print(f":white_check_mark: Finished step [bold]{class_name}[/bold]. Output shape={result.dataf.shape}. Time taken for step: {time_taken}. :white_check_mark:")
        return result
    return wrapper

# Cell
@typechecked
class CopyPreProcessor(BaseProcessor):
    """Copy DataFrame to avoid manipulation of original DataFrame. """
    def __init__(self):
        super(CopyPreProcessor, self).__init__()

    @display_processor_info
    def transform(self, dataset: Dataset, *args, **kwargs) -> Dataset:
        return dataset.copy_dataset()

@typechecked
class GroupStatsPreProcessor(BaseProcessor):
    """
    WARNING: Only supported for Version 1 (legacy) data.
    Calculate group statistics for all data groups.
    """
    def __init__(self):
        super(GroupStatsPreProcessor, self).__init__()
        self.group_names = ["intelligence", "wisdom", "charisma",
                            "dexterity", "strength", "constitution"]

    @display_processor_info
    def transform(self, dataset: Dataset, *args, **kwargs) -> Dataset:
        self._check_data_validity(dataset=dataset)
        dataset.dataf = dataset.dataf.pipe(self._add_group_features)
        return Dataset(**dataset.__dict__)

    def _add_group_features(self, dataf: pd.DataFrame) -> pd.DataFrame:
        """ Mean, standard deviation and skew for each group. """
        for group in self.group_names:
            cols = [col for col in df.columns if group in col]
            dataf[f"feature_{group}_mean"] = dataf[cols].mean(axis=1)
            dataf[f"feature_{group}_std"] = dataf[cols].std(axis=1)
            dataf[f"feature_{group}_skew"] = dataf[cols].skew(axis=1)
        return dataf


    def _check_data_validity(self, dataset: Dataset):
        assert hasattr(dataset, 'version'), f"Version should be specified for '{self.__class__.__name__}' This Preprocessor will only work on version 1 data."
        assert getattr(dataset, 'version') == 1, f"'{self.__class__.__name__}' only works on version 1 data. Got version: '{getattr(dataset, 'version')}'."
