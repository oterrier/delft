import itertools
import re
import collections
import numpy as np
np.random.seed(7)
#from tensorflow import set_random_seed
#set_random_seed(7)
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.externals import joblib

import delft.utilities.bert.tokenization as tokenization
from delft.utilities.Tokenizer import tokenizeAndFilterSimple

import tensorflow as tf
tf.set_random_seed(7)

# this is derived from https://github.com/Hironsan/anago/blob/master/anago/preprocess.py

UNK = '<UNK>'
PAD = '<PAD>'

case_index = {'<PAD>': 0, 'numeric': 1, 'allLower':2, 'allUpper':3, 'initialUpper':4, 'other':5, 'mainly_numeric':6, 'contains_digit': 7}


class WordPreprocessor(BaseEstimator, TransformerMixin):

    def __init__(self,
                 use_char_feature=True,
                 padding=True,
                 return_lengths=True, 
                 return_casing=False, 
                 return_features=False, 
                 max_char_length=30
                 ):

        self.use_char_feature = use_char_feature
        self.padding = padding
        self.return_lengths = return_lengths
        self.return_casing = return_casing
        self.return_features = return_features
        self.vocab_char = None
        self.vocab_tag  = None
        self.vocab_case = [k for k, v in case_index.items()]
        self.max_char_length = max_char_length

    def fit(self, X, y):
        chars = {PAD: 0, UNK: 1}
        tags  = {PAD: 0}

        for w in set(itertools.chain(*X)): 
            if not self.use_char_feature:
                continue
            for c in w:
                if c not in chars:
                    chars[c] = len(chars)

        for t in itertools.chain(*y):
            if t not in tags:
                tags[t] = len(tags)

        self.vocab_char = chars
        self.vocab_tag  = tags

        return self

    def transform(self, X, y=None, extend=False):
        """
        transforms input into sequence
        the optional boolean `extend` indicates that we need to avoid sequence of length 1 alone in a batch 
        (which would cause an error with tf)

        Args:
            X: list of list of word tokens
            y: list of list of tags

        Returns:
            numpy array: sentences with char sequences, and optionally length, casing and custom features  
            numpy array: sequence of tags
        """
        chars = []
        lengths = []
        for sent in X:
            char_ids = []
            lengths.append(len(sent))
            for w in sent:
                if self.use_char_feature:
                    char_ids.append(self.get_char_ids(w))
                    if extend:
                        char_ids.append([])

            if self.use_char_feature:
                chars.append(char_ids)

        if y is not None:
            y = [[self.vocab_tag[t] for t in sent] for sent in y]
            if extend:
                y[0].append(self.vocab_tag[PAD])

        if self.padding:
            sents, y = self.pad_sequence(chars, y)
        else:
            sents = [chars]

        # optional additional information
        # lengths
        if self.return_lengths:
            lengths = np.asarray(lengths, dtype=np.int32)
            lengths = lengths.reshape((lengths.shape[0], 1))
            sents.append(lengths)

        return (sents, y) if y is not None else sents

    def inverse_transform(self, y):
        """
        send back original label string
        """
        indice_tag = {i: t for t, i in self.vocab_tag.items()}
        return [indice_tag[y_] for y_ in y]

    def get_char_ids(self, word):
        return [self.vocab_char.get(c, self.vocab_char[UNK]) for c in word]

    def pad_sequence(self, char_ids, labels=None):
        if labels:
            labels, _ = pad_sequences(labels, 0)
            labels = np.asarray(labels)
            labels = dense_to_one_hot(labels, len(self.vocab_tag), nlevels=2)

        if self.use_char_feature:
            char_ids, word_lengths = pad_sequences(char_ids, pad_tok=0, nlevels=2, max_char_length=self.max_char_length)
            char_ids = np.asarray(char_ids)
            return [char_ids], labels
        else:
            return labels

    def save(self, file_path):
        joblib.dump(self, file_path)

    @classmethod
    def load(cls, file_path):
        p = joblib.load(file_path)
        return p


def _pad_sequences(sequences, pad_tok, max_length):
    """
    Args:
        sequences: a generator of list or tuple.
        pad_tok: the char to pad with.

    Returns:
        a list of list where each sublist has same length.
    """
    sequence_padded, sequence_length = [], []

    for seq in sequences:
        seq = list(seq)
        seq_ = seq[:max_length] + [pad_tok] * max(max_length - len(seq), 0)
        sequence_padded += [seq_]
        sequence_length += [min(len(seq), max_length)]

    return sequence_padded, sequence_length


def pad_sequences(sequences, pad_tok=0, nlevels=1, max_char_length=30):
    """
    Args:
        sequences: a generator of list or tuple.
        pad_tok: the char to pad with.

    Returns:
        a list of list where each sublist has same length.
    """
    if nlevels == 1:
        max_length = len(max(sequences, key=len))
        sequence_padded, sequence_length = _pad_sequences(sequences, pad_tok, max_length)
    elif nlevels == 2:
        max_length_word = max_char_length
        sequence_padded, sequence_length = [], []
        for seq in sequences:
            # all words are same length now
            sp, sl = _pad_sequences(seq, pad_tok, max_length_word)
            sequence_padded += [sp]
            sequence_length += [sl]

        max_length_sentence = max(map(lambda x: len(x), sequences))
        sequence_padded, _ = _pad_sequences(sequence_padded, [pad_tok] * max_length_word, max_length_sentence)
        sequence_length, _ = _pad_sequences(sequence_length, 0, max_length_sentence)
    else:
        raise ValueError('nlevels can take 1 or 2, not take {}.'.format(nlevels))

    return sequence_padded, sequence_length


def dense_to_one_hot(labels_dense, num_classes, nlevels=1):
    """
    Convert class labels from scalars to one-hot vectors
    """
    if nlevels == 1:
        num_labels = labels_dense.shape[0]
        index_offset = np.arange(num_labels) * num_classes
        labels_one_hot = np.zeros((num_labels, num_classes), dtype=np.int32)
        labels_one_hot.flat[index_offset + labels_dense.ravel()] = 1
        return labels_one_hot
    elif nlevels == 2:
        # assume that labels_dense has same column length
        num_labels = labels_dense.shape[0]
        num_length = labels_dense.shape[1]
        labels_one_hot = np.zeros((num_labels, num_length, num_classes), dtype=np.int32)
        layer_idx = np.arange(num_labels).reshape(num_labels, 1)
        # this index selects each component separately
        component_idx = np.tile(np.arange(num_length), (num_labels, 1))
        # then we use `a` to select indices according to category label
        labels_one_hot[layer_idx, component_idx, labels_dense] = 1
        return labels_one_hot
    else:
        raise ValueError('nlevels can take 1 or 2, not take {}.'.format(nlevels))


def prepare_preprocessor(X, y, model_config):
    p = WordPreprocessor(max_char_length=model_config.max_char_length)
    p.fit(X, y)

    return p


def to_vector_single(tokens, embeddings, maxlen, lowercase=False, num_norm=True):
    """
    Given a list of tokens convert it to a sequence of word embedding 
    vectors with the provided embeddings, introducing <PAD> and <UNK> padding token
    vector when appropriate
    """
    window = tokens[-maxlen:]

    # TBD: use better initializers (uniform, etc.) 
    x = np.zeros((maxlen, embeddings.embed_size), )

    # TBD: padding should be left and which vector do we use for padding? 
    # and what about masking padding later for RNN?
    for i, word in enumerate(window):
        if lowercase:
            word = _lower(word)
        if num_norm:
            word = _normalize_num(word)
        x[i,:] = embeddings.get_word_vector(word).astype('float32')

    return x


def to_vector_elmo(tokens, embeddings, maxlen, lowercase=False, num_norm=False, extend=False):
    """
    Given a list of tokens convert it to a sequence of word embedding 
    vectors based on ELMo contextualized embeddings
    """
    subtokens = get_subtokens(tokens, maxlen, extend, lowercase)
    return embeddings.get_sentence_vector_only_ELMo(subtokens)
    """
    if use_token_dump:
        return embeddings.get_sentence_vector_ELMo_with_token_dump(tokens)
    """


def get_subtokens(tokens, maxlen, extend=False, lowercase=False):
    """
    Extract the token list and eventually lowercase or truncate longest sequences

    :param tokens: input tokens
    :param maxlen: maximum length for each sub_token
    :param extend: when set to true, sub tokens will be padded with an additional element
    :param lowercase: when set to true the sub_tokens will be lowercased
    :return:
    """
    subtokens = []
    for i in range(0, len(tokens)):
        local_tokens = []
        for j in range(0, min(len(tokens[i]), maxlen)):
            if lowercase:
                local_tokens.append(_lower(tokens[i][j]))
            else:
                local_tokens.append(tokens[i][j])
        if extend:
            local_tokens.append(UNK)
        subtokens.append(local_tokens)
    return subtokens


def to_vector_simple_with_elmo(tokens, embeddings, maxlen, lowercase=False, num_norm=False, extend=False):
    """
    Given a list of tokens convert it to a sequence of word embedding 
    vectors based on the concatenation of the provided static embeddings and 
    the ELMo contextualized embeddings, introducing <PAD> and <UNK> 
    padding token vector when appropriate
    """
    subtokens = get_subtokens(tokens, maxlen, extend, lowercase)
    return embeddings.get_sentence_vector_with_ELMo(subtokens)


def to_vector_bert(tokens, embeddings, maxlen, lowercase=False, num_norm=False, extend=False):
    """
    Given a list of tokens convert it to a sequence of word embedding 
    vectors based on the BERT contextualized embeddings, introducing
    padding token when appropriate
    """
    subtokens = get_subtokens(tokens, maxlen, extend, lowercase)
    vector = embeddings.get_sentence_vector_only_BERT(subtokens)
    return vector


def to_vector_simple_with_bert(tokens, embeddings, maxlen, lowercase=False, num_norm=False, extend=False):
    """
    Given a list of tokens convert it to a sequence of word embedding 
    vectors based on the concatenation of the provided static embeddings and 
    the BERT contextualized embeddings, introducing padding token vector 
    when appropriate
    """
    subtokens = get_subtokens(tokens, maxlen, extend, lowercase)
    return embeddings.get_sentence_vector_with_BERT(subtokens)


def to_casing_single(tokens, maxlen):
    """
    Given a list of tokens set the casing, introducing <PAD> and <UNK> padding 
    when appropriate
    """
    window = tokens[-maxlen:]

    # TBD: use better initializers (uniform, etc.) 
    x = np.zeros((maxlen), )

    # TBD: padding should be left and which vector do we use for padding? 
    # and what about masking padding later for RNN?
    for i, word in enumerate(window):
        x[i] = float(_casing(word))

    return x


def _casing(word):   
        casing = 'other'

        numDigits = 0
        for char in word:
            if char.isdigit():
                numDigits += 1
        digitFraction = numDigits / float(len(word))

        if word.isdigit():
            casing = 'numeric'
        elif digitFraction > 0.5:
            casing = 'mainly_numeric'
        elif word.islower(): 
            casing = 'allLower'
        elif word.isupper(): 
            casing = 'allUpper'
        elif word[0].isupper(): 
            casing = 'initialUpper'
        elif numDigits > 0:
            casing = 'contains_digit'

        return case_index[casing]


def _lower(word):
    return word.lower() 


def _normalize_num(word):
    return re.sub(r'[0-9０１２３４５６７８９]', r'0', word)

class InputExample(object):
    """
    A single training/test example for simple BERT sequence classification.
    """
    def __init__(self,
                 guid,
                 tokens,
                 labels=None):
        """Constructs a InputExample.
        Args:
          guid: Unique id for the example.
          tokens: list of tokens (strings)
          label: list of string. The labels of the example. This should be
            specified for train and dev examples, but not for test examples.
        """
        self.guid = guid
        self.tokens = tokens
        self.labels = labels

class InputFeatures(object):
    """
    A single BERT set of features of data.
    """
    def __init__(self,
                 input_ids,
                 input_mask,
                 segment_ids,
                 label_ids):
        self.input_ids = input_ids
        self.input_mask = input_mask
        self.segment_ids = segment_ids
        self.label_ids = label_ids     

class NERProcessor(object):
    """
    General BERT processor for a sequence labelling data set.
    This is simply feed by the DeLFT sequence labelling data obtained by the 
    custom DeLFT readers. 
    """
    def __init__(self,
                labels):
        self.labels = labels
    
    def get_train_examples(self, x, y):
        """
        Gets a collection of `InputExample`s for the train set
        """
        return self._get_example(x, y)
    
    def get_dev_examples(self, x, y):
        """
        Gets a collection of `InputExample`s for the dev set
        """
        return self._get_example(x, y)
    
    def get_test_examples(self, x, y):
        """
        Gets a collection of `InputExample`s for the test set
        """
        return self._get_example(x, y)
    
    def get_labels(self):
        """
        Gets the list of labels for this data set
        """
        return self.labels

    def _get_example(self, x, y):
        """
        Gets a collection of `InputExample` already labelled (for training and eval)
        """
        examples = []
        for i in range(len(x)):
            guid = i
            tokens = []
            labels = []
            for j in range(len(x[i])):
                tokens.append(tokenization.convert_to_unicode(x[i][j]))
                labels.append(tokenization.convert_to_unicode(y[i][j]))
            example = InputExample(guid=guid, tokens=tokens, labels=labels)
            examples.append(example)
        return examples

    def create_inputs(self, x_s, dummy_label='O'):
        """
        Gets a collection of `InputExample` for input to be labelled (for prediction)
        """
        examples = []
        # dummy label to avoid breaking the BERT base code
        for (i, x) in enumerate(x_s):
            guid = i
            tokens = []
            labels = []
            # if x is not already segmented:
            if isinstance(x, list):
                simple_tokens = x
            else:
                simple_tokens = tokenizeAndFilterSimple(x)                
            for j in range(len(simple_tokens)):
                tokens.append(tokenization.convert_to_unicode(simple_tokens[j]))
                labels.append(tokenization.convert_to_unicode(dummy_label))
            examples.append(InputExample(guid=guid, tokens=tokens, labels=labels))
        return examples


def convert_single_example(ex_index, example, label_list, max_seq_length, tokenizer):
    """
    Converts a single BERT `InputExample` into a single BERT `InputFeatures`.

    The BERT tokenization is introduced which will modify sentence and labels as 
    follow:
    tokens: [Jim,Hen,##son,was,a,puppet,##eer]
    labels: [I-PER,I-PER,X,O,O,O,X]
    """

    text_tokens = example.tokens
    tokens = []
    # the following is to better keep track of additional tokens added by BERT tokenizer, 
    # only some of them has a prefix ## that allows to identify them downstream in the process
    tokens_marked = []
    label_tokens = example.labels
    labels = []    

    label_map = {}
    #here start with zero this means that "[PAD]" is zero
    for (i,label) in enumerate(label_list):
        label_map[label] = i

    for text_token, label_token in zip(text_tokens, label_tokens):
        text_sub_tokens = tokenizer.tokenize(text_token)
        text_sub_tokens_marked = tokenizer.tokenize(text_token)
        for i in range(len(text_sub_tokens_marked)):
            if i == 0:
                continue
            tok = text_sub_tokens_marked[i]
            if not tok.startswith("##"):
                text_sub_tokens_marked[i] = "##" + tok
        label_sub_tokens = [label_token] + ["X"] * (len(text_sub_tokens) - 1)
        tokens.extend(text_sub_tokens)
        tokens_marked.extend(text_sub_tokens_marked)
        labels.extend(label_sub_tokens)

    if len(tokens) >= max_seq_length - 2:
        tokens = tokens[0:(max_seq_length - 2)]
        tokens_marked = tokens_marked[0:(max_seq_length - 2)]
        labels = labels[0:(max_seq_length - 2)]

    input_tokens = []
    input_tokens_marked = []
    segment_ids = []
    label_ids = []

    # The convention in BERT is:
    # (a) For sequence pairs:
    #  tokens:   [CLS] is this jack ##son ##ville ? [SEP] no it is not . [SEP]
    #  type_ids: 0     0  0    0    0     0       0 0     1  1  1  1   1 1
    # (b) For single sequences:
    #  tokens:   [CLS] the dog is hairy . [SEP]
    #  type_ids: 0     0   0   0  0     0 0
    #
    # Where "type_ids" are used to indicate whether this is the first sequence 
    # or the second sequence. 
    
    input_tokens.append("[CLS]")
    input_tokens_marked.append("[CLS]")
    segment_ids.append(0)
    label_ids.append(label_map["[CLS]"])

    for i, token in enumerate(tokens):
        input_tokens.append(token)
        segment_ids.append(0)
        label_ids.append(label_map[labels[i]])

    for token in tokens_marked:
        input_tokens_marked.append(token)

    # note: do we really need to add "[SEP]" for single sequence? 
    input_tokens.append("[SEP]")
    input_tokens_marked.append("[SEP]")
    segment_ids.append(0)
    label_ids.append(label_map["[SEP]"])

    input_ids = tokenizer.convert_tokens_to_ids(input_tokens)

    # The mask has 1 for real tokens and 0 for padding tokens
    input_mask = [1] * len(input_ids)
    
    # Zero-pad up to the sequence length.
    while len(input_ids) < max_seq_length:
        input_ids.append(0)
        input_mask.append(0)
        segment_ids.append(0)
        label_ids.append(0)

    assert len(input_ids) == max_seq_length
    assert len(input_mask) == max_seq_length
    assert len(segment_ids) == max_seq_length
    assert len(label_ids) == max_seq_length
    
    if ex_index < 5:
        tf.logging.info("*** Example ***")
        tf.logging.info("guid: %s" % (example.guid))
        tf.logging.info("tokens: %s" % " ".join([tokenization.printable_text(x) for x in tokens]))
        tf.logging.info("input_ids: %s" % " ".join([str(x) for x in input_ids]))
        tf.logging.info("input_mask: %s" % " ".join([str(x) for x in input_mask]))
        tf.logging.info("segment_ids: %s" % " ".join([str(x) for x in segment_ids]))
        tf.logging.info("label_ids: %s" % " ".join([str(x) for x in label_ids]))

    feature = InputFeatures(
        input_ids=input_ids,
        input_mask=input_mask,
        segment_ids=segment_ids,
        label_ids=label_ids)

    return feature, input_tokens_marked

def file_based_input_fn_builder(input_file, seq_length, is_training, drop_remainder, batch_size):
    """
    Creates an `input_fn` closure to be passed to TPUEstimator
    """
    name_to_features = {
        "input_ids": tf.FixedLenFeature([seq_length], tf.int64),
        "input_mask": tf.FixedLenFeature([seq_length], tf.int64),
        "segment_ids": tf.FixedLenFeature([seq_length], tf.int64),
        "label_ids": tf.FixedLenFeature([seq_length], tf.int64),
    }

    def _decode_record(record, name_to_features):
        """Decodes a record to a TensorFlow example."""
        example = tf.parse_single_example(record, name_to_features)

        # int32 cast 
        for name in list(example.keys()):
            t = example[name]
            if t.dtype == tf.int64:
                t = tf.to_int32(t)
            example[name] = t
        
        return example

    def input_fn(params):
        """
        the actual input function
        """
        # For training, we want a lot of parallel reading and shuffling.
        # For eval, we want no shuffling and parallel reading doesn't matter.
        d = tf.data.TFRecordDataset(input_file)
        if is_training:
            d = d.repeat()
            d = d.shuffle(buffer_size=100)

        d = d.apply(
          tf.data.experimental.map_and_batch(
                lambda record: _decode_record(record, name_to_features),
                batch_size=batch_size,
                drop_remainder=drop_remainder))

        return d

    return input_fn

def input_fn_generator(generator, seq_length, batch_size):
    """
    Creates an `input_fn` closure to be passed to the estimator
    """
    def input_fn(params):
        output_types = {
          "input_ids": tf.int64,
          "input_mask": tf.int64,
          "segment_ids": tf.int64,
          "label_ids": tf.int64
        }

        output_shapes = {
          "input_ids": tf.TensorShape([None, seq_length]),
          "input_mask": tf.TensorShape([None, seq_length]),
          "segment_ids": tf.TensorShape([None, seq_length]),
          "label_ids": tf.TensorShape([None, seq_length])
        }

        return tf.data.Dataset.from_generator(generator, output_types=output_types, output_shapes=output_shapes)

    return input_fn

def file_based_convert_examples_to_features(examples, label_list, max_seq_length, tokenizer, output_file):
    """
    Convert a list of `InputExample` to a list of bert `InputFeatures` in a file.
    This is used when training to avoid re-doing this conversion other multiple epochs.
    For prediction, we don't want to use a file. 
    """
    writer = tf.python_io.TFRecordWriter(output_file)
    for (ex_index, example) in enumerate(examples):
        if ex_index % 5000 == 0:
            tf.logging.info("Writing example %d of %d" % (ex_index, len(examples)))
        feature,_ = convert_single_example(ex_index, example, label_list, max_seq_length, tokenizer)

        def create_int_feature(values):
            f = tf.train.Feature(int64_list=tf.train.Int64List(value=list(values)))
            return f

        features = collections.OrderedDict()
        features["input_ids"] = create_int_feature(feature.input_ids)
        features["input_mask"] = create_int_feature(feature.input_mask)
        features["segment_ids"] = create_int_feature(feature.segment_ids)
        features["label_ids"] = create_int_feature(feature.label_ids)
        tf_example = tf.train.Example(features=tf.train.Features(feature=features))
        writer.write(tf_example.SerializeToString())

    # sentence token in each batch
    writer.close()

def convert_examples_to_features(examples, label_list, max_seq_length, tokenizer):
    """
    Convert a list of `InputExample` to be labelled into a list of bert `InputFeatures`
    """
    features = []
    input_tokens = []
    for (ex_index, example) in enumerate(examples):
        feature, tokens = convert_single_example(ex_index, example, label_list,
                                         max_seq_length, tokenizer)
        features.append(feature)
        input_tokens.append(tokens)
    return features, input_tokens
