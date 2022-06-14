from __future__ import annotations
from typing import Iterable
import pandas as pd
from sklearn.linear_model import LinearRegression
from psyke.regression import Limit, MinUpdate, ZippedDimension, Expansion
from random import Random
import numpy as np
from psyke import get_default_random_seed
from psyke.regression.utils import Dimension, Dimensions


class FeatureNotFoundException(Exception):

    def __init__(self, feature: str):
        super().__init__('Feature "' + feature + '" not found.')


class HyperCube:
    """
    A N-dimensional cube holding a numeric value.
    """

    # TODO: this should be configurable by the designer
    EPSILON = 1.0 / 1000  # Precision used when comparing two hypercubes

    def __init__(self, dimension: dict[str, tuple] = None, limits: set[Limit] = None,
                 output: float | LinearRegression = 0.0):
        self._dimensions = dimension if dimension is not None else {}
        self.__limits = limits if limits is not None else set()
        self._output = output
        self._diversity = 0.0

    def __contains__(self, point: dict[str, float]) -> bool:
        """
        Note that a point (dict[str, float]) is inside a hypercube if ALL its dimensions' values satisfy:
            min_dim <= value < max_dim
        :param point: a N-dimensional point
        :return: true if the point is inside the hypercube, false otherwise
        """
        return all([(self.get_first(k) <= v < self.get_second(k)) for k, v in point.items()])

    def __eq__(self, other: HyperCube) -> bool:
        return all([(abs(dimension.this_dimension[0] - dimension.other_dimension[0]) < HyperCube.EPSILON)
                    & (abs(dimension.this_dimension[1] - dimension.other_dimension[1]) < HyperCube.EPSILON)
                    for dimension in self.__zip_dimensions(other)])

    def __getitem__(self, feature: str) -> Dimension:
        if feature in self._dimensions.keys():
            return self._dimensions[feature]
        else:
            raise FeatureNotFoundException(feature)

    def __setitem__(self, key, value) -> None:
        self._dimensions[key] = value

    def __hash__(self) -> int:
        result = [hash(name + str(dimension[0]) + str(dimension[1])) for name, dimension in self.dimensions.items()]
        return sum(result)

    @property
    def dimensions(self) -> Dimensions:
        return self._dimensions

    @property
    def limit_count(self) -> int:
        return len(self.__limits)

    @property
    def output(self) -> float | LinearRegression:
        return self._output

    @property
    def diversity(self) -> float:
        return self._diversity

    def __expand_one(self, update: MinUpdate, surrounding: HyperCube, ratio: float = 1.0) -> None:
        self.update_dimension(update.name, (
            max(self.get_first(update.name) - update.value / ratio, surrounding.get_first(update.name)),
            min(self.get_second(update.name) + update.value / ratio, surrounding.get_second(update.name))
        ))

    def _filter_dataframe(self, dataset: pd.DataFrame) -> pd.DataFrame:
        v = np.array([v for _, v in self._dimensions.items()])
        ds = dataset.to_numpy(copy=True)
        indices = np.all((ds >= v[:, 0]) & (ds < v[:, 1]), axis=1)
        return dataset[indices]

    def __zip_dimensions(self, hypercube: HyperCube) -> list[ZippedDimension]:
        return [ZippedDimension(dimension, self[dimension], hypercube[dimension])
                for dimension in self._dimensions.keys()]

    def add_limit(self, limit_or_feature: Limit | str, direction: str = None) -> None:
        if isinstance(limit_or_feature, Limit):
            self.__limits.add(limit_or_feature)
        else:
            self.add_limit(Limit(limit_or_feature, direction))

    def check_limits(self, feature: str) -> str | None:
        filtered = [limit for limit in self.__limits if limit.feature == feature]
        if len(filtered) == 0:
            return None
        if len(filtered) == 1:
            return filtered[0].direction
        if len(filtered) == 2:
            return '*'
        raise Exception('Too many limits for this feature')

    def create_samples(self, n: int = 1, generator: Random = Random(get_default_random_seed())) -> pd.DataFrame:
        return pd.DataFrame([self.__create_tuple(generator) for _ in range(n)])

    @staticmethod
    def check_overlap(to_check: Iterable[HyperCube], hypercubes: Iterable[HyperCube]) -> bool:
        checked = []
        to_check_copy = list(to_check).copy()
        while len(to_check_copy) > 0:
            cube = to_check_copy.pop()
            for hypercube in hypercubes:
                if hypercube not in checked and cube.overlap(hypercube):
                    return True
            checked += [cube]
        return False

    def copy(self) -> HyperCube:
        return HyperCube(self.dimensions.copy(), self.__limits.copy(), self.output)

    def count(self, dataset: pd.DataFrame) -> int:
        return self._filter_dataframe(dataset.iloc[:, :-1]).shape[0]

    @staticmethod
    def create_surrounding_cube(dataset: pd.DataFrame) -> HyperCube:
        return HyperCube({
            column: (min(dataset[column]) - HyperCube.EPSILON ** 2, max(dataset[column]) + HyperCube.EPSILON ** 2)
            for column in dataset.columns[:-1]
        })

    def __create_tuple(self, generator: Random) -> dict:
        return {k: generator.uniform(self.get_first(k), self.get_second(k)) for k in self._dimensions.keys()}

    @staticmethod
    def cube_from_point(point: dict) -> HyperCube:
        return HyperCube({k: (v, v) for k, v in list(point.items())[:-1]}, output=list(point.values())[-1])

    def equal(self, hypercubes: Iterable[HyperCube] | HyperCube) -> bool:
        if isinstance(hypercubes, Iterable):
            return any([self.equal(cube) for cube in hypercubes])
        else:
            return all([(abs(dimension.this_dimension[0] - dimension.other_dimension[0]) < HyperCube.EPSILON)
                        & (abs(dimension.this_dimension[1] - dimension.other_dimension[1]) < HyperCube.EPSILON)
                        for dimension in self.__zip_dimensions(hypercubes)])

    def expand(self, expansion: Expansion, hypercubes: Iterable[HyperCube]) -> None:
        feature = expansion.feature
        a, b = self[feature]
        self.update_dimension(feature, expansion.boundaries(a, b))
        other_cube = self.overlap(hypercubes)
        if isinstance(other_cube, HyperCube):
            self.update_dimension(feature, (other_cube.get_second(feature), b)
                                  if expansion.direction == '-' else (a, other_cube.get_first(feature)))
        if isinstance(self.overlap(hypercubes), HyperCube):
            raise Exception('Overlapping not handled')

    def expand_all(self, updates: Iterable[MinUpdate], surrounding: HyperCube, ratio: float = 1.0) -> None:
        for update in updates:
            self.__expand_one(update, surrounding, ratio)

    def get_first(self, feature: str) -> float:
        return self[feature][0]

    def get_second(self, feature: str) -> float:
        return self[feature][1]

    def has_volume(self) -> bool:
        return all([dimension[1] - dimension[0] > HyperCube.EPSILON for dimension in self._dimensions.values()])

    def is_adjacent(self, cube: HyperCube) -> str | None:
        adjacent = None
        for (feature, [a1, b1]) in self._dimensions.items():
            if self[feature] == cube[feature]:
                continue
            [a2, b2] = cube[feature]
            if (adjacent is not None) or ((b1 != a2) and (b2 != a1)):
                return None
            adjacent = feature
        return adjacent

    def merge_along_dimension(self, cube: HyperCube, feature: str) -> HyperCube:
        new_cube = self.copy()
        (a1, b1) = self[feature]
        (a2, b2) = cube[feature]
        new_cube.update_dimension(feature, (min(a1, a2), max(b1, b2)))
        return new_cube

    # TODO: maybe two different methods are more readable and easier to debug
    def overlap(self, hypercubes: Iterable[HyperCube] | HyperCube) -> HyperCube | bool | None:
        if isinstance(hypercubes, Iterable):
            for hypercube in hypercubes:
                if (self != hypercube) & self.overlap(hypercube):
                    return hypercube
            return None
        elif self is hypercubes:
            return False
        else:
            return all([not ((dimension.other_dimension[0] >= dimension.this_dimension[1]) |
                             (dimension.this_dimension[0] >= dimension.other_dimension[1]))
                        for dimension in self.__zip_dimensions(hypercubes)])

    # TODO: maybe two different methods are more readable and easier to debug
    def update_dimension(self, feature: str, lower: float | tuple[float, float], upper: float | None = None) -> None:
        if upper is None:
            self[feature] = lower
        else:
            self.update_dimension(feature, (lower, upper))

    def update(self, dataset: pd.DataFrame, predictor) -> None:
        filtered = self._filter_dataframe(dataset.iloc[:, :-1])
        predictions = predictor.predict(filtered)
        self._output = np.mean(predictions)
        self._diversity = np.std(predictions)

    # TODO: why this is not a property?
    def init_std(self, std: float) -> None:
        self._diversity = std


class RegressionCube(HyperCube):
    def __init__(self):
        super().__init__(output=LinearRegression())

    def update(self, dataset: pd.DataFrame, predictor) -> None:
        filtered = self._filter_dataframe(dataset.iloc[:, :-1])
        if len(filtered > 0):
            predictions = predictor.predict(filtered)
            self._output.fit(filtered, predictions)
            self._diversity = (abs(self._output.predict(filtered) - predictions)).mean()