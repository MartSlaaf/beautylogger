from collections import defaultdict
from history import History
from canvas import Canvas
import numpy as np

import torch
from numbers import Number

from tqdm import tqdm

class BeautyLogger:
    #TODO: add comments
    #TODO: add more conveniency in calculation and agregation
    #TODO: add overridable aggregators?
    #TODO: add tests

    def __init__(self, aggregable=None, calculable=None, plots=None, progressbar='none', prints=None, print_mode='last', trackable=None, tracking_mode=None):
        """
        Class for logging of training process parameters. Could also aggregate metrics, plot or print them for you.
        Args:
            aggregable (dict): parameters to be aggregated. Key should be name of parameter, value should be either 'mean', 'max' or callable to get aggregate.
            calculable (list): parameters to be aggregated via complex function. Every list element should be tuple: (list of input parameters names, output parameter name, aggregating function)
            plots (list): plots to be shown. Every list element should be a tuple: (type of plot, list of parameters to plot)
            progressbar (str): could be either 'none' for no progress bar at all, 'epochs' for progress over epochs, 'steps' for progress bar over steps or 'both' for both steps and epochs progressbars.
            prints (list): parameters to be printed. Each element should be either string (parameter name) or pair (parameter name, mode: 'max'/'min'). If mode setted, maximum or minimum achieved value will be printed
            trackable (str): parameter name to track for early stopping or model saving. Is required for functions is_best and steps_without_progress
        """
        self.aggregable = aggregable if aggregable is not None else {}
        self.calculable = calculable
        if self.calculable is not None:
            self.calculable_inputs = [c[0] for c in self.calculable]
        else:
            self.calculable_inputs = []

        self.plots = plots
        if prints is not None:
            self.prints = self._initialize_prints(prints)
        else:
            self.prints = None
        self.prin_mode = print_mode

        self.inter_epoch = defaultdict(lambda:defaultdict(list))

        self.epochs = History()
        if self.plots is not None:
            self.canvas = Canvas()

        self.epochs_progressbar = None
        self.steps_progressbar = None

        self.trackable = trackable
        self.tracking_mode = np.max if tracking_mode == 'max' else np.min

        if progressbar in ['epochs', 'both']:
            self.epochs_progressbar = tqdm()
        if progressbar in ['steps', 'both']:
            self.steps_progressbar = tqdm()

        self.step = 0

    def _initialize_prints(self, prints):
        new_prints = []
        for element in prints:
            if isinstance(element, tuple):
                if element[1] == 'max':
                    new_prints.append((element[0], np.max))
                elif element[1] == 'min':
                    new_prints.append((element[0], np.min))
                else:
                    raise ValueError(f'Unknown printing mode {element[1]}')
            else:
                new_prints.append((element, None))

    def _get_value(self, value):
        if isinstance(value, torch.Tensor):
            return value.detach().cpu().numpy()
        else:
            return value

    def log_step(self, step_type='train', **kwargs):
        for param, value in kwargs.items():
            self.inter_epoch[step_type][param].append(self._get_value(value))

    def _concat_param(self, param_tile):
        if isinstance(param_tile[0], np.ndarray):
            return np.concatenate(param_tile, 0)
        elif isinstance(param_tile[0], Number):
            return np.array(param_tile)
        else:
            raise ValueError(f'Unknown type of parameter values {type(param_tile[0])}')

    def is_best(self, trackable=None, tracking_mode=None):
        if (self.trackable is None) and (trackable is None):
            raise Exception('Best epoch could be estimated only with setted trackable parameter. Set it on initialization or pass to this function.')
        if (self.tracking_mode is None) and (tracking_mode is None):
            raise Exception('Best epoch could be estimated only with setted tracking mode. Set it on initialization or pass to this function.')
        else:
            if tracking_mode is not None:
                tracking_mode = np.max if tracking_mode == 'max' else np.min
            else:
                tracking_mode = self.tracking_mode
        trackable = trackable if trackable is not None else self.trackable
        track = self.epochs[trackable].data
        return track[-1] == tracking_mode(track)

    def steps_without_progress(self, trackable=None, tracking_mode=None):
        if (self.trackable is None) and (trackable is None):
            raise Exception('Steps without progress could be estimated only with setted trackable parameter. Set it on initialization or pass to this function.')
        if (self.tracking_mode is None) and (tracking_mode is None):
            raise Exception('Steps without progress could be estimated only with setted tracking mode. Set it on initialization or pass to this function.')
        else:
            if tracking_mode is not None:
                tracking_mode = np.max if tracking_mode == 'max' else np.min
            else:
                tracking_mode = self.tracking_mode
        trackable = trackable if trackable is not None else self.trackable

        track = self.epochs[trackable].data
        best_value = tracking_mode(track)
        return len(track) - (np.where(track==best_value)[0][-1] + 1)




    def _concat_params(self, step_type, param_names):
        return [self._concat_param(self.inter_epoch[step_type][par_n]) for par_n in param_names]

    def agg_epoch(self, step_type='train'):
        # add mean as default aggregation if param is not used anywhere
        for param in self.inter_epoch[step_type].keys():
            if (param not in self.aggregable.keys()) and (param not in self.calculable_inputs):
                self.aggregable[param] = 'mean'

        # aggregate all params meant in aggregable
        # TODO: move definition to init
        if self.aggregable is not None:
            agg_funcs, agg_params = [], []
            for param, agg_type in self.aggregable.items():
                if agg_type == 'mean':
                    func_to_agg = np.mean
                elif agg_type == 'max':
                    func_to_agg = np.max
                elif callable(agg_type):
                    func_to_agg = agg_type
                else:
                    raise ValueError('aggregation type expected to be "mean", "max" or callable')
                agg_funcs.append(func_to_agg)
                agg_params.append(param)

            self.epochs.log(self.step, **{step_type+'_'+n: f(p) for p,f,n in zip(self._concat_params(step_type, agg_params), agg_funcs, agg_params)})

        if self.calculable is not None:
            for input_params, output_param, convert_function in self.calculable:
                self.epochs.log(self.step, **{step_type+'_'+output_param: convert_function(*self._concat_params(step_type, input_params))})

    def log_epoch(self, **kwargs):
        for step_type in self.inter_epoch.keys():
            self.agg_epoch(step_type)

        self.epochs.log(self.step, **kwargs)

        self.step += 1
        self.inter_epoch = defaultdict(lambda:defaultdict(list))

    def plot(self):
        with self.canvas:
            for plot_type, plot_elements in self.plots:
                if plot_type == 'plot':
                    self.canvas.draw_plot([self.epochs[p_e] for p_e in plot_elements])
                elif plot_type == 'summary':
                    self.canvas.draw_summary(self.epochs)
                else:
                    raise NotImplemented('plot types other than summary and plot are not supported yet!')

    def print(self):
        if self.print_mode == 'last':
            string_to_write = ''
            for param, modifier in self.prints:
                value = self.epochs[param].data[-1]
                if modifier is not None:
                    best_value = modifier(self.epochs[param].data)
                    string_to_write += f'{value:.3} ({best_value:.3})\t'
                else:
                    string_to_write += f'{value:.3}\t'

            if self.epochs_progressbar is not None:
                self.epochs_progressbar.write(string_to_write, end='\r')
            elif self.steps_progressbar is not None:
                self.steps_progressbar.write(string_to_write, end='\r')
            else:
                print(string_to_write, end='\r')
        elif self.print_mode == 'all':
            pass
        elif self.print_mode == 'exponential':
            pass