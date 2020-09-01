# Copyright 2017-2018 Ben Lambert

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""
Primary code for computing word error rate and other metrics from ASR output.
"""
from __future__ import division

from functools import reduce
from collections import defaultdict
from edit_distance import SequenceMatcher

from termcolor import colored

# Some defaults
print_instances_p = False
print_errors_p = False
files_head_ids = False
files_tail_ids = False
confusions = False
min_count = 0
wer_vs_length_p = True

# For keeping track of word error rates by sentence length
# this is so we can see if performance is better/worse for longer
# and/or shorter sentences
lengths = []
error_rates = []
wer_bins = defaultdict(list)
wer_vs_length = defaultdict(list)
# Tables for keeping track of which words get confused with one another
insertion_table = defaultdict(int)
deletion_table = defaultdict(int)
substitution_table = defaultdict(int)
# These are the editdistance opcodes that are condsidered 'errors'
error_codes = ['replace', 'delete', 'insert']


class AsrEvaluationResults(dict):
    def __getattr__(self, name):
        return self[name]


# TODO - rename this function.  Move some of it into evaluate.py?
def main(args):
    """Main method - this reads the hyp and ref files, and creates
    editdistance.SequenceMatcher objects to compute the edit distance.
    All the statistics necessary statistics are collected, and results are
    printed as specified by the command line options.

    This function doesn't not check to ensure that the reference and
    hypothesis file have the same number of lines.  It will stop after the
    shortest one runs out of lines.  This should be easy to fix...
    """
    results = evaluate(args)

    if confusions:
        print_confusions()
    if wer_vs_length_p:
        print_wer_vs_length()

    print('Sentence count: {}'.format(results.sentence_count))
    print('WER: {:10.3%} ({:10d} / {:10d})'.format(results.wer, results.error_count, results.ref_token_count))
    print('WRR: {:10.3%} ({:10d} / {:10d})'.format(results.wrr, results.match_count, results.ref_token_count))
    print('SER: {:10.3%} ({:10d} / {:10d})'.format(results.ser, results.sent_error_count, results.sentence_count))


def evaluate(args):
    set_global_variables(args)

    ref_token_count = 0
    match_count = 0
    error_count = 0
    sent_error_count = 0

    line_count = 0
    # Loop through each line of the reference and hyp file
    for ref_line, hyp_line in zip(args.ref, args.hyp):
        processed_p, ref_length, matches, errors = process_line_pair(ref_line, hyp_line, line_count,
                                                                     case_insensitive=args.case_insensitive,
                                                                     remove_empty_refs=args.remove_empty_refs)
        if processed_p:
            line_count += 1
            ref_token_count += ref_length
            match_count += matches
            error_count += errors

            if errors != 0:
                sent_error_count += 1

    # Compute WER and WRR
    if ref_token_count > 0:
        wrr = match_count / ref_token_count
        wer = error_count / ref_token_count
    else:
        wrr = 0.0
        wer = 0.0
    # Compute SER
    if line_count > 0:
        ser = sent_error_count / line_count
    else:
        ser = 0.0

    substitutions = map(lambda item: {'ref': item[0][0], 'hyp': item[0][1], 'count': item[1]},
                        substitution_table.items())
    return AsrEvaluationResults({
        'sentence_count': line_count,
        'ref_token_count': ref_token_count,
        'match_count': match_count,
        'error_count': error_count,
        'sent_error_count': sent_error_count,
        'wer': wer,
        'wrr': wrr,
        'ser': ser,
        'insertions': insertion_table,
        'deletions': deletion_table,
        'substitutions': list(substitutions)
    })


def process_line_pair(ref_line, hyp_line, line_count, case_insensitive=False, remove_empty_refs=False):
    """Given a pair of strings corresponding to a reference and hypothesis,
    compute the edit distance, print if desired, and keep track of results
    in global variables.

    Return true if the pair was counted, false if the pair was not counted due
    to an empty reference string.

    Also returns the ref token count, match count, and error count for this line pair."""

    # Split into tokens by whitespace
    ref = ref_line.split()
    hyp = hyp_line.split()
    id_ = None

    # If the files have IDs, then split the ID off from the text
    if files_head_ids:
        id_ = ref[0]
        ref, hyp = remove_head_id(ref, hyp)
    elif files_tail_ids:
        id_ = ref[-1]
        ref, hyp = remove_tail_id(ref, hyp)

    if case_insensitive:
        ref = list(map(str.lower, ref))
        hyp = list(map(str.lower, hyp))
    if remove_empty_refs and len(ref) == 0:
        return False, 0, 0, 0

    # Create an object to get the edit distance, and then retrieve the
    # relevant counts that we need.
    sm = SequenceMatcher(a=ref, b=hyp)
    errors = get_error_count(sm)
    matches = get_match_count(sm)
    ref_length = len(ref)

    # If we're keeping track of which words get mixed up with which others, call track_confusions
    if confusions:
        track_confusions(sm, ref, hyp)

    # If we're printing instances, do it here (in roughly the align.c format)
    if print_instances_p or (print_errors_p and errors != 0):
        print_instances(ref, hyp, sm, line_count, id_=id_)

    # Keep track of the individual error rates, and reference lengths, so we
    # can compute average WERs by sentence length
    lengths.append(ref_length)
    if len(ref) > 0:
        error_rate = errors * 1.0 / len(ref)
    else:
        error_rate = float("inf")
    error_rates.append(error_rate)
    wer_bins[len(ref)].append(error_rate)
    return True, ref_length, matches, errors


def set_global_variables(args):
    """Copy argparse args into global variables."""
    global print_instances_p
    global print_errors_p
    global files_head_ids
    global files_tail_ids
    global confusions
    global min_count
    global wer_vs_length_p
    # Put the command line options into global variables.
    print_instances_p = args.print_instances
    print_errors_p = args.print_errors
    files_head_ids = args.head_ids
    files_tail_ids = args.tail_ids
    confusions = args.confusions
    min_count = args.min_word_count
    wer_vs_length_p = args.print_wer_vs_length


def remove_head_id(ref, hyp):
    """Assumes that the ID is the begin token of the string which is common
    in Kaldi but not in Sphinx."""
    ref_id = ref[0]
    hyp_id = hyp[0]
    if ref_id != hyp_id:
        print('Reference and hypothesis IDs do not match! '
              'ref="{}" hyp="{}"\n'
              'File lines in hyp file should match those in the ref file.'.format(ref_id, hyp_id))
        exit(-1)
    ref = ref[1:]
    hyp = hyp[1:]
    return ref, hyp


def remove_tail_id(ref, hyp):
    """Assumes that the ID is the final token of the string which is common
    in Sphinx but not in Kaldi."""
    ref_id = ref[-1]
    hyp_id = hyp[-1]
    if ref_id != hyp_id:
        print('Reference and hypothesis IDs do not match! '
              'ref="{}" hyp="{}"\n'
              'File lines in hyp file should match those in the ref file.'.format(ref_id, hyp_id))
        exit(-1)
    ref = ref[:-1]
    hyp = hyp[:-1]
    return ref, hyp


def print_instances(ref, hyp, sm, line_count, id_=None):
    """Print a single instance of a ref/hyp pair."""
    ref_sentence, hyp_sentence = get_diffs(sm, ref, hyp)
    print(ref_sentence)
    print(hyp_sentence)

    if id_:
        print(('SENTENCE {0:d}  {1!s}'.format(line_count + 1, id_)))
    else:
        print('SENTENCE {0:d}'.format(line_count + 1))
    # Handle cases where the reference is empty without dying
    if len(ref) != 0:
        correct_rate = sm.matches() / len(ref)
        error_rate = sm.distance() / len(ref)
    elif sm.matches() == 0:
        correct_rate = 1.0
        error_rate = 0.0
    else:
        correct_rate = 0.0
        error_rate = sm.matches()
    print('Correct          = {0:6.1%}  {1:3d}   ({2:6d})'.format(correct_rate, sm.matches(), len(ref)))
    print('Errors           = {0:6.1%}  {1:3d}   ({2:6d})'.format(error_rate, sm.distance(), len(ref)))


def track_confusions(sm, seq1, seq2):
    """Keep track of the errors in a global variable, given a sequence matcher."""
    opcodes = sm.get_opcodes()
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == 'insert':
            for i in range(j1, j2):
                word = seq2[i]
                insertion_table[word] += 1
        elif tag == 'delete':
            for i in range(i1, i2):
                word = seq1[i]
                deletion_table[word] += 1
        elif tag == 'replace':
            for w1 in seq1[i1:i2]:
                for w2 in seq2[j1:j2]:
                    key = (w1, w2)
                    substitution_table[key] += 1


def print_confusions():
    """Print the confused words that we found... grouped by insertions, deletions
    and substitutions."""
    if len(insertion_table) > 0:
        print('INSERTIONS:')
        for item in sorted(list(insertion_table.items()), key=lambda x: x[1], reverse=True):
            if item[1] >= min_count:
                print('{0:20s} {1:10d}'.format(*item))
    if len(deletion_table) > 0:
        print('DELETIONS:')
        for item in sorted(list(deletion_table.items()), key=lambda x: x[1], reverse=True):
            if item[1] >= min_count:
                print('{0:20s} {1:10d}'.format(*item))
    if len(substitution_table) > 0:
        print('SUBSTITUTIONS:')
        for [w1, w2], count in sorted(list(substitution_table.items()), key=lambda x: x[1], reverse=True):
            if count >= min_count:
                print('{0:20s} -> {1:20s}   {2:10d}'.format(w1, w2, count))


# TODO - For some reason I was getting two different counts depending on how I count the matches,
# so do an assertion in this code to make sure we're getting matching counts.
# This might slow things down.
def get_match_count(sm):
    "Return the number of matches, given a sequence matcher object."
    matches = None
    matches1 = sm.matches()
    matching_blocks = sm.get_matching_blocks()
    matches2 = reduce(lambda x, y: x + y, [x[2] for x in matching_blocks], 0)
    assert matches1 == matches2
    matches = matches1
    return matches


def get_error_count(sm):
    """Return the number of errors (insertion, deletion, and substitutiions
    , given a sequence matcher object."""
    opcodes = sm.get_opcodes()
    errors = [x for x in opcodes if x[0] in error_codes]
    error_lengths = [max(x[2] - x[1], x[4] - x[3]) for x in errors]
    return reduce(lambda x, y: x + y, error_lengths, 0)


# TODO - This is long and ugly.  Perhaps we can break it up?
def get_diffs(sm, seq1, seq2, prefix1='REF:', prefix2='HYP:', suffix1=None, suffix2=None):
    """Given a sequence matcher and the two sequences, returns the Sphinx-style
    'diff' of the two strings."""
    ref_tokens = []
    hyp_tokens = []
    opcodes = sm.get_opcodes()
    for tag, i1, i2, j1, j2 in opcodes:
        # If they are equal, do nothing except lowercase them
        if tag == 'equal':
            for i in range(i1, i2):
                ref_tokens.append(seq1[i].lower())
            for i in range(j1, j2):
                hyp_tokens.append(seq2[i].lower())
        # For insertions and deletions, put a filler of '***' on the other one, and
        # make the other all caps
        elif tag == 'delete':
            for i in range(i1, i2):
                ref_token = colored(seq1[i].upper(), 'red')
                ref_tokens.append(ref_token)
            for i in range(i1, i2):
                hyp_token = colored('*' * len(seq1[i]), 'red')
                hyp_tokens.append(hyp_token)
        elif tag == 'insert':
            for i in range(j1, j2):
                ref_token = colored('*' * len(seq2[i]), 'red')
                ref_tokens.append(ref_token)
            for i in range(j1, j2):
                hyp_token = colored(seq2[i].upper(), 'red')
                hyp_tokens.append(hyp_token)
        # More complicated logic for a substitution
        elif tag == 'replace':
            seq1_len = i2 - i1
            seq2_len = j2 - j1
            # Get a list of tokens for each
            s1 = list(map(str.upper, seq1[i1:i2]))
            s2 = list(map(str.upper, seq2[j1:j2]))
            # Pad the two lists with False values to get them to the same length
            if seq1_len > seq2_len:
                for i in range(0, seq1_len - seq2_len):
                    s2.append(False)
            if seq1_len < seq2_len:
                for i in range(0, seq2_len - seq1_len):
                    s1.append(False)
            assert len(s1) == len(s2)
            # Pair up words with their substitutions, or fillers
            for i in range(0, len(s1)):
                w1 = s1[i]
                w2 = s2[i]
                # If we have two words, make them the same length
                if w1 and w2:
                    if len(w1) > len(w2):
                        s2[i] = w2 + ' ' * (len(w1) - len(w2))
                    elif len(w1) < len(w2):
                        s1[i] = w1 + ' ' * (len(w2) - len(w1))
                # Otherwise, create an empty filler word of the right width
                if not w1:
                    s1[i] = '*' * len(w2)
                if not w2:
                    s2[i] = '*' * len(w1)
            s1 = map(lambda x: colored(x, 'red'), s1)
            s2 = map(lambda x: colored(x, 'red'), s2)
            ref_tokens += s1
            hyp_tokens += s2
    if prefix1: ref_tokens.insert(0, prefix1)
    if prefix2: hyp_tokens.insert(0, prefix2)
    if suffix1: ref_tokens.append(suffix1)
    if suffix2: hyp_tokens.append(suffix2)

    return ' '.join(ref_tokens), ' '.join(hyp_tokens)


def mean(seq):
    """Return the average of the elements of a sequence."""
    return float(sum(seq)) / len(seq) if len(seq) > 0 else float('nan')


def print_wer_vs_length():
    """Print the average word error rate for each length sentence."""
    avg_wers = {length: mean(wers) for length, wers in wer_bins.items()}
    for length, avg_wer in sorted(avg_wers.items(), key=lambda x: (x[1], x[0])):
        print('{0:5d} {1:f}'.format(length, avg_wer))
    print('')
