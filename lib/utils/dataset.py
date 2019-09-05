import numpy as np
import os
import platform
import random

from .data_point import DataPoint
from . import file_utils as f
from . import sequence as seq


class Dataset:

    @classmethod
    def load_from_file(cls, file_path):
        file = open(file_path)
        datapoint_set = set()

        branch = cls.branch_from_filepath(file_path)
        category = os.path.basename(file_path)

        for line in file:
            key, string_value = line.split("\t", 1)
            datapoint_set.add(DataPoint.load(key, string_value))

        return cls(branch, category=category, datapoint_set=datapoint_set)

    @classmethod
    def branch_from_filepath(cls, file_path):
        dirname = os.path.dirname(file_path)
        if platform.system() == 'Windows':
            dirs = dirname.split('\\')
        else:
            dirs = dirname.split('/')
        return dirs[-1]

    @classmethod
    def split_by_chr(cls, dataset, chrs_by_category):
        split_sets = {}
        final_datasets = {}
        categories_by_chr = cls.reverse_chrs_dictionary(chrs_by_category)

        # separate original dictionary by categories
        for datapoint in dataset.datapoint_set:
            category = categories_by_chr[datapoint.chrom_name]
            if category not in split_sets.keys(): split_sets.update({category: set()})
            split_sets[category].add(datapoint)

        # create Dataset objects from separated dictionaries
        for category, set_ in split_sets.items():
            # TODO maybe unnecessary to use category as a key, as it's saved as datasets attribute
            final_datasets.update({category: Dataset(dataset.branch, category=category, datapoint_set=set_)})

        return final_datasets

    @classmethod
    def reverse_chrs_dictionary(cls, dictionary):
        reversed_dict = {}
        for key, chrs in dictionary.items():
            for chr in chrs:
                reversed_dict.update({chr: key})

        return reversed_dict

    @classmethod
    def split_random(cls, dataset, ratio_list, seed=56):
        # so far the categories are fixed, not sure if there would be need for custom categories
        categories_ratio = {'train': float(ratio_list[0]),
                            'validation': float(ratio_list[1]),
                            'test': float(ratio_list[2]),
                            'blackbox': float(ratio_list[3])}

        random.seed(seed)
        randomized = list(dataset.datapoint_set)
        random.shuffle(randomized)

        dataset_size = len(dataset.datapoint_set)
        total = sum(categories_ratio.values())
        split_datasets = {}
        start = 0
        end = 0

        # TODO ? to assure whole numbers, we round down the division, which leads to lost of several samples. Fix it?
        for category, ratio in categories_ratio.items():
            size = int(dataset_size * ratio / total)
            end += (size - 1)
            dp_set = set(randomized[start:end])
            split_datasets.update({category: Dataset(dataset.branch, category=category, datapoint_set=dp_set)})
            start += size

        return split_datasets

    @classmethod
    def merge(cls, list_of_datasets):
        merged_datapoint_set = set()
        branch = list_of_datasets[0].branch
        category = list_of_datasets[0].category
        for dataset in list_of_datasets:
            merged_datapoint_set.update(dataset.datapoint_set)

        return cls(branch, category=category, datapoint_set=merged_datapoint_set)

    def __init__(self, klass=None, branches=None, category=None, bed_file=None, ref_files=None, strand=None, encoding=None,
                 datapoint_set=None):
        self.branches = branches  # list of seq, cons or fold branches
        self.klass = klass  # e.g. positive or negative
        self.category = category  # train, validation, test or blackbox for separated datasets

        # TODO is there a way a folding branch could use already converted datasets from seq branch, if available?
        # TODO complementarity currently applied only to sequence. Does the conservation score depend on strand?

        if datapoint_set:
            self.datapoint_set = datapoint_set
        else:
            self.datapoint_set = self.map_bed_to_refs(branches, klass, bed_file, ref_files, encoding, strand)

        # TODO make it work
        if self.branch == 'fold' and not datapoint_set:
            # can the result really be a dictionary? probably should
            file_name = self.branch + "_" + klass
            self.datapoint_set = seq.fold(self.datapoint_set, self.branch, file_name)

    def save_to_file(self, dir_path, file_name):
        content = ""
        content += 'key' + "\t" + "\t".join(self.branches) + "\n"
        for datapoint in self.datapoint_set:
            content += datapoint.key() + "\t"
            for branch in self.branches:
                content += datapoint.string_value(branch) + "\t"
            content += "\n"

        file_path = os.path.join(dir_path, file_name)
        f.write(file_path, content.strip())
        return file_path

    def reduce(self, ratio, seed=84):
        random.seed(seed)
        randomized = list(self.datapoint_set)
        random.shuffle(randomized)
        last = int(len(randomized) * ratio)

        reduced_dp_set = set(randomized[0:last])

        self.datapoint_set = reduced_dp_set
        return self

    def values(self, branch):
        # return ordered list of values of datapoints
        values = []
        for datapoint in self.datapoint_set:
            values.append(datapoint.branches_value[branch])

        return np.array(values)

    def labels(self, alphabet=None):
        # return ordered list of values of datapoints
        labels = []
        for datapoint in self.datapoint_set:
            labels.append(datapoint.klass)

        if alphabet:
            encoded_labels = [seq.translate(item, alphabet) for item in labels]
            return np.array(encoded_labels)
        else:
            return np.array(labels)

    # def export_to_bed(self, path):
    #     return f.dictionary_to_bed(self.dictionary, path)
    #
    # def export_to_fasta(self, path):
    #     return f.dictionary_to_fasta(self.dictionary, path)

    @staticmethod
    def map_bed_to_refs(branches, klass, bed_file, ref_files, encoding, strand):
        file = f.filehandle_for(bed_file)
        final_set = set()

        for line in file:
            values = line.split()

            chrom_name = values[0]
            seq_start = values[1]
            seq_end = values[2]
            try:
                strand_sign = values[5]
            except:
                strand_sign = None
            branches_values = {}

            for branch in branches:
                # TODO adjust so that it gets translated only once for seq and branch together
                complement = branch == 'seq' or branch == 'fold'
                ref_dictionary = ref_files[branch]

                if chrom_name in ref_dictionary.keys():
                    # first position in chromosome in bed file is assigned as 0 (thus it fits the python indexing from 0)
                    start_position = int(seq_start)
                    # both bed file coordinates and python range exclude the last position
                    end_position = int(seq_end)
                    sequence = []
                    for i in range(start_position, end_position):
                        sequence.append(ref_dictionary[chrom_name][i])

                    if complement and strand and strand_sign == '-':
                        sequence = seq.complement(sequence, seq.DNA_COMPLEMENTARY)

                    if encoding and branch == 'seq':
                        sequence = [seq.translate(item, encoding) for item in sequence]

                    branches_values.update({branch: np.array(sequence)})

            # Save the point only if the value is available for all the branches
            if len(branches_values) == len(branches):
                final_set.add(DataPoint(branches, klass, chrom_name, seq_start, seq_end, strand_sign, branches_values))

        return final_set
