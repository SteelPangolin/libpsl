#!/usr/bin/env python
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE.chromium file.

"""
A Deterministic acyclic finite state automaton (DAFSA) is a compact
representation of an unordered word list (dictionary).

http://en.wikipedia.org/wiki/Deterministic_acyclic_finite_state_automaton

This python program converts a list of strings to a byte array in C++.
This python program fetches strings and return values from a gperf file
and generates a C++ file with a byte array representing graph that can be
used as a memory efficient replacement for the perfect hash table.

The input strings are assumed to consist of printable 7-bit ASCII characters
and the return values are assumed to be one digit integers.

In this program a DAFSA is a diamond shaped graph starting at a common
source node and ending at a common sink node. All internal nodes contain
a label and each word is represented by the labels in one path from
the source node to the sink node.

The following python represention is used for nodes:

  Source node: [ children ]
  Internal node: (label, [ children ])
  Sink node: None

The graph is first compressed by prefixes like a trie. In the next step
suffixes are compressed so that the graph gets diamond shaped. Finally
one to one linked nodes are replaced by nodes with the labels joined.

The order of the operations is crucial since lookups will be performed
starting from the source with no backtracking. Thus a node must have at
most one child with a label starting by the same character. The output
is also arranged so that all jumps are to increasing addresses, thus forward
in memory.

The generated output has suffix free decoding so that the sign of leading
bits in a link (a reference to a child node) indicate if it has a size of one,
two or three bytes and if it is the last outgoing link from the actual node.
A node label is terminated by a byte with the leading bit set.

The generated byte array can described by the following BNF:

<byte> ::= < 8-bit value in range [0x00-0xFF] >

<char> ::= < printable 7-bit ASCII character, byte in range [0x20-0x7F] >
<end_char> ::= < char + 0x80, byte in range [0xA0-0xFF] >
<return value> ::= < value + 0x80, byte in range [0x80-0x8F] >

<offset1> ::= < byte in range [0x00-0x3F] >
<offset2> ::= < byte in range [0x40-0x5F] >
<offset3> ::= < byte in range [0x60-0x7F] >

<end_offset1> ::= < byte in range [0x80-0xBF] >
<end_offset2> ::= < byte in range [0xC0-0xDF] >
<end_offset3> ::= < byte in range [0xE0-0xFF] >

<prefix> ::= <char>

<label> ::= <end_char>
          | <char> <label>

<end_label> ::= <return_value>
          | <char> <end_label>

<offset> ::= <offset1>
           | <offset2> <byte>
           | <offset3> <byte> <byte>

<end_offset> ::= <end_offset1>
               | <end_offset2> <byte>
               | <end_offset3> <byte> <byte>

<offsets> ::= <end_offset>
            | <offset> <offsets>

<source> ::= <offsets>

<node> ::= <label> <offsets>
         | <prefix> <node>
         | <end_label>

<dafsa> ::= <source>
          | <dafsa> <node>

Decoding:

<char> -> printable 7-bit ASCII character
<end_char> & 0x7F -> printable 7-bit ASCII character
<return value> & 0x0F -> integer
<offset1 & 0x3F> -> integer
((<offset2> & 0x1F>) << 8) + <byte> -> integer
((<offset3> & 0x1F>) << 16) + (<byte> << 8) + <byte> -> integer

end_offset1, end_offset2 and and_offset3 are decoded same as offset1,
offset2 and offset3 respectively.

The first offset in a list of offsets is the distance in bytes between the
offset itself and the first child node. Subsequent offsets are the distance
between previous child node and next child node. Thus each offset links a node
to a child node. The distance is always counted between start addresses, i.e.
first byte in decoded offset or first byte in child node.

Example 1:

%%
aa, 1
a, 2
%%

The input is first parsed to a list of words:
["aa1", "a2"]

A fully expanded graph is created from the words:
source = [node1, node4]
node1 = ("a", [node2])
node2 = ("a", [node3])
node3 = ("\x01", [sink])
node4 = ("a", [node5])
node5 = ("\x02", [sink])
sink = None

Compression results in the following graph:
source = [node1]
node1 = ("a", [node2, node3])
node2 = ("\x02", [sink])
node3 = ("a\x01", [sink])
sink = None

A C++ representation of the compressed graph is generated:

const unsigned char dafsa[7] = {
  0x81, 0xE1, 0x02, 0x81, 0x82, 0x61, 0x81,
};

The bytes in the generated array has the following meaning:

 0: 0x81 <end_offset1>  child at position 0 + (0x81 & 0x3F) -> jump to 1

 1: 0xE1 <end_char>     label character (0xE1 & 0x7F) -> match "a"
 2: 0x02 <offset1>      child at position 2 + (0x02 & 0x3F) -> jump to 4

 3: 0x81 <end_offset1>  child at position 4 + (0x81 & 0x3F) -> jump to 5
 4: 0x82 <return_value> 0x82 & 0x0F -> return 2

 5: 0x61 <char>         label character 0x61 -> match "a"
 6: 0x81 <return_value> 0x81 & 0x0F -> return 1

Example 2:

%%
aa, 1
bbb, 2
baa, 1
%%

The input is first parsed to a list of words:
["aa1", "bbb2", "baa1"]

Compression results in the following graph:
source = [node1, node2]
node1 = ("b", [node2, node3])
node2 = ("aa\x01", [sink])
node3 = ("bb\x02", [sink])
sink = None

A C++ representation of the compressed graph is generated:

const unsigned char dafsa[11] = {
  0x02, 0x83, 0xE2, 0x02, 0x83, 0x61, 0x61, 0x81, 0x62, 0x62, 0x82,
};

The bytes in the generated array has the following meaning:

 0: 0x02 <offset1>      child at position 0 + (0x02 & 0x3F) -> jump to 2
 1: 0x83 <end_offset1>  child at position 2 + (0x83 & 0x3F) -> jump to 5

 2: 0xE2 <end_char>     label character (0xE2 & 0x7F) -> match "b"
 3: 0x02 <offset1>      child at position 3 + (0x02 & 0x3F) -> jump to 5
 4: 0x83 <end_offset1>  child at position 5 + (0x83 & 0x3F) -> jump to 8

 5: 0x61 <char>         label character 0x61 -> match "a"
 6: 0x61 <char>         label character 0x61 -> match "a"
 7: 0x81 <return_value> 0x81 & 0x0F -> return 1

 8: 0x62 <char>         label character 0x62 -> match "b"
 9: 0x62 <char>         label character 0x62 -> match "b"
10: 0x82 <return_value> 0x82 & 0x0F -> return 2
"""

import sys

class InputError(Exception):
  """Exception raised for errors in the input file."""


def to_dafsa(words):
  """Generates a DAFSA from a word list and returns the source node.

  Each word is split into characters so that each character is represented by
  a unique node. It is assumed the word list is not empty.
  """
  if not words:
    raise InputError('The domain list must not be empty')
  def ToNodes(word):
    """Split words into characters"""
    if not 0x1F < ord(word[0]) < 0x80:
      raise InputError('Domain names must be printable 7-bit ASCII')
    if len(word) == 1:
      return chr(ord(word[0]) & 0x0F), [None]
    return word[0], [ToNodes(word[1:])]
  return [ToNodes(word) for word in words]


def to_words(node):
  """Generates a word list from all paths starting from an internal node."""
  if not node:
    return ['']
  return [(node[0] + word) for child in node[1] for word in to_words(child)]


def reverse(dafsa):
  """Generates a new DAFSA that is reversed, so that the old sink node becomes
  the new source node.
  """
  sink = []
  nodemap = {}

  def dfs(node, parent):
    """Creates reverse nodes.

    A new reverse node will be created for each old node. The new node will
    get a reversed label and the parents of the old node as children.
    """
    if not node:
      sink.append(parent)
    elif id(node) not in nodemap:
      nodemap[id(node)] = (node[0][::-1], [parent])
      for child in node[1]:
        dfs(child, nodemap[id(node)])
    else:
      nodemap[id(node)][1].append(parent)

  for node in dafsa:
    dfs(node, None)
  return sink


def join_labels(dafsa):
  """Generates a new DAFSA where internal nodes are merged if there is a one to
  one connection.
  """
  parentcount = { id(None): 2 }
  nodemap = { id(None): None }

  def count_parents(node):
    """Count incoming references"""
    if id(node) in parentcount:
      parentcount[id(node)] += 1
    else:
      parentcount[id(node)] = 1
      for child in node[1]:
        count_parents(child)

  def join(node):
    """Create new nodes"""
    if id(node) not in nodemap:
      children = [join(child) for child in node[1]]
      if len(children) == 1 and parentcount[id(node[1][0])] == 1:
        child = children[0]
        nodemap[id(node)] = (node[0] + child[0], child[1])
      else:
        nodemap[id(node)] = (node[0], children)
    return nodemap[id(node)]

  for node in dafsa:
    count_parents(node)
  return [join(node) for node in dafsa]


def join_suffixes(dafsa):
  """Generates a new DAFSA where nodes that represent the same word lists
  towards the sink are merged.
  """
  nodemap = { frozenset(('',)): None }

  def join(node):
    """Returns a macthing node. A new node is created if no matching node
    exists. The graph is accessed in dfs order.
    """
    suffixes = frozenset(to_words(node))
    if suffixes not in nodemap:
      nodemap[suffixes] = (node[0], [join(child) for child in node[1]])
    return nodemap[suffixes]

  return [join(node) for node in dafsa]


def top_sort(dafsa):
  """Generates list of nodes in topological sort order."""
  incoming = {}

  def count_incoming(node):
    """Counts incoming references."""
    if node:
      if id(node) not in incoming:
        incoming[id(node)] = 1
        for child in node[1]:
          count_incoming(child)
      else:
        incoming[id(node)] += 1

  for node in dafsa:
    count_incoming(node)

  for node in dafsa:
    incoming[id(node)] -= 1

  waiting = [node for node in dafsa if incoming[id(node)] == 0]
  nodes = []

  while waiting:
    node = waiting.pop()
    assert incoming[id(node)] == 0
    nodes.append(node)
    for child in node[1]:
      if child:
        incoming[id(child)] -= 1
        if incoming[id(child)] == 0:
          waiting.append(child)
  return nodes


def encode_links(children, offsets, current):
  """Encodes a list of children as one, two or three byte offsets."""
  if not children[0]:
    # This is an <end_label> node and no links follow such nodes
    assert len(children) == 1
    return []
  guess = 3 * len(children)
  assert children
  children = sorted(children, key = lambda x: -offsets[id(x)])
  while True:
    offset = current + guess
    buf = []
    for child in children:
      last = len(buf)
      distance = offset - offsets[id(child)]
      assert distance > 0 and distance < (1 << 21)

      if distance < (1 << 6):
        # A 6-bit offset: "s0xxxxxx"
        buf.append(distance)
      elif distance < (1 << 13):
        # A 13-bit offset: "s10xxxxxxxxxxxxx"
        buf.append(0x40 | (distance >> 8))
        buf.append(distance & 0xFF)
      else:
        # A 21-bit offset: "s11xxxxxxxxxxxxxxxxxxxxx"
        buf.append(0x60 | (distance >> 16))
        buf.append((distance >> 8) & 0xFF)
        buf.append(distance & 0xFF)
      # Distance in first link is relative to following record.
      # Distance in other links are relative to previous link.
      offset -= distance
    if len(buf) == guess:
      break
    guess = len(buf)
  # Set most significant bit to mark end of links in this node.
  buf[last] |= (1 << 7)
  buf.reverse()
  return buf


def encode_prefix(label):
  """Encodes a node label as a list of bytes without a trailing high byte.

  This method encodes a node if there is exactly one child  and the
  child follows immidiately after so that no jump is needed. This label
  will then be a prefix to the label in the child node.
  """
  assert label
  return [ord(c) for c in reversed(label)]


def encode_label(label):
  """Encodes a node label as a list of bytes with a trailing high byte >0x80.
  """
  buf = encode_prefix(label)
  # Set most significant bit to mark end of label in this node.
  buf[0] |= (1 << 7)
  return buf


def encode(dafsa):
  """Encodes a DAFSA to a list of bytes"""
  output = []
  offsets = {}

  for node in reversed(top_sort(dafsa)):
    if (len(node[1]) == 1 and node[1][0] and
        (offsets[id(node[1][0])] == len(output))):
      output.extend(encode_prefix(node[0]))
    else:
      output.extend(encode_links(node[1], offsets, len(output)))
      output.extend(encode_label(node[0]))
    offsets[id(node)] = len(output)

  output.extend(encode_links(dafsa, offsets, len(output)))
  output.reverse()
  return output


def to_cxx(data):
  """Generates C++ code from a list of encoded bytes."""
  text = '/* This file is generated. DO NOT EDIT!\n\n'
  text += 'The byte array encodes effective tld names. See make_dafsa.py for'
  text += ' documentation.'
  text += '*/\n\n'
  text += 'static const unsigned char kDafsa[%s] = {\n' % len(data)
  for i in range(0, len(data), 12):
    text += '  '
    text += ', '.join('0x%02x' % byte for byte in data[i:i + 12])
    text += ',\n'
  text += '};\n'
  return text


def words_to_whatever(words, converter):
  """Generates C++ code from a word list"""
  dafsa = to_dafsa(words)
  for fun in (reverse, join_suffixes, reverse, join_suffixes, join_labels):
    dafsa = fun(dafsa)
  return converter(encode(dafsa))


def words_to_cxx(words):
  """Generates C++ code from a word list"""
  return words_to_whatever(words, to_cxx)


def words_to_binary(words):
  """Generates C++ code from a word list"""
  return words_to_whatever(words, bytearray)


def parse_gperf(infile):
  """Parses gperf file and extract strings and return code"""
  lines = [line.strip() for line in infile]
  # Extract strings after the first '%%' and before the second '%%'.
  #begin = lines.index('%%') + 1
  #end = lines.index('%%', begin)
  #lines = lines[begin:end]
  for line in lines:
    if line[-3:-1] != ', ':
      raise InputError('Expected "domainname, <digit>", found "%s"' % line)
    # Technically the DAFSA format could support return values in range [0-31],
    # but the values below are the only with a defined meaning.
    if line[-1] not in '0123456789ABCDEF':
      raise InputError('Expected value to be one of {0,1,2,4,5}, found "%s"' %
                       line[-1])
  return [line[:-3] + line[-1] for line in lines]


def main():
  if len(sys.argv) < 3:
    print('usage: %s [--binary] infile outfile' % sys.argv[0])
    return 1

  argpos = 1
  converter = words_to_cxx

  if sys.argv[argpos] == '--binary':
    converter = words_to_binary
    argpos += 1

  if sys.argv[argpos] == '-':
    with open(sys.argv[argpos + 1], 'w') as outfile:
      outfile.write(converter(parse_gperf(sys.stdin)))
  else:
    with open(sys.argv[argpos], 'r') as infile, open(sys.argv[argpos + 1], 'w') as outfile:
      outfile.write(converter(parse_gperf(infile)))

  return 0


if __name__ == '__main__':
  sys.exit(main())
