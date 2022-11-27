""" Convert HTML to slate, slate to HTML

A port of volto-slate' deserialize.js module
"""

import json
import re
from collections import deque

from lxml.html import html5parser

from .config import DEFAULT_BLOCK_TYPE, KNOWN_BLOCK_TYPES


def tag_name(el):
    """tag_name.

    :param el:
    """
    return el.tag.replace("{%s}" % el.nsmap["html"], "")


def is_inline(el):
    """Returns true if the element is a text node

    Some richtext editors provide support for "inline elements", which is to
    say they mark some portions of text and add flags for that, like
    "bold:true,italic:true", etc.

    From experience, this is a bad way to go when the output is intended to be
    HTML. In HTML DOM there is only markup and that markup is semantic. So
    keeping it purely markup greately simplifies the number of cases that need
    to be covered.
    """

    if isinstance(el, dict) and "text" in el:
        return True

    return False


def merge_adjacent_text_nodes(children):
    "Given a list of Slate elements, it combines adjacent texts nodes"

    ranges = []
    for i, v in enumerate(children):
        if "text" in v:
            if ranges and ranges[-1][1] == i - 1:
                ranges[-1][1] = i
            else:
                ranges.append([i, i])
    text_positions = []
    range_dict = {}
    for start, end in ranges:
        text_positions.extend(list(range(start, end + 1)))
        range_dict[start] = end

    result = []
    for i, v in enumerate(children):
        if i not in text_positions:
            result.append(v)
        if i in range_dict:
            result.append(
                {"text": "".join([c["text"] for c in children[i : range_dict[i] + 1]])}
            )
    return result


SPACE_BEFORE_ENDLINE = re.compile(r"\s+\n", re.M)
SPACE_AFTER_DEADLINE = re.compile(r"\n\s+", re.M)
TAB = re.compile(r"\t", re.M)
LINEBREAK = re.compile(r"\n", re.M)
MULTIPLE_SPACE = re.compile(r" ( +)", re.M)
FIRST_SPACE = re.compile("^ ", re.M)
FIRST_ANY_SPACE = re.compile(r"^\s", re.M)
FIRST_ALL_SPACE = re.compile(r"^\s+", re.M)
ANY_SPACE_AT_END = re.compile(r"\s$", re.M)


def remove_space_before_after_endline(text):
    text = SPACE_BEFORE_ENDLINE.sub("\n", text)
    text = SPACE_AFTER_DEADLINE.sub("\n", text)
    return text


def convert_tabs_to_spaces(text):
    return TAB.sub(" ", text)


def convert_linebreaks_to_spaces(text):
    return LINEBREAK.sub(" ", text)


def remove_space_follow_space(text, node):
    # // Any space immediately following another space (even across two separate
    # // inline elements) is ignored (rule 4)
    # text = text.replace(/ ( +)/gm, ' ');
    # if (!text.startsWith(' ')) return text;
    #
    # if (node.previousSibling) {
    #   if (node.previousSibling.nodeType === TEXT_NODE) {
    #     if (node.previousSibling.textContent.endsWith(' ')) {
    #       return text.replace(/^ /, '');
    #     }
    #   } else if (isInline(node.previousSibling)) {
    #     const prevText = collapseInlineSpace(node.previousSibling);
    #     if (prevText.endsWith(' ')) {
    #       return text.replace(/^ /, '');
    #     }
    #   }
    # } else {
    #   const parent = node.parentNode;
    #   if (parent.previousSibling) {
    #     //  && isInline(parent.previousSibling)
    #     const prevText = collapseInlineSpace(parent.previousSibling);
    #     if (prevText && prevText.endsWith(' ')) {
    #       return text.replace(/^ /, '');
    #     }
    #   }
    # }
    #
    # return text;
    text = MULTIPLE_SPACE.sub(" ", text)

    if not text.startswith(" "):
        return text

    previous = node.getprevious()
    if previous is None:
        head = node.getparent().text
        if head.endswith(" "):
            text = FIRST_SPACE.sub("", text)
    else:
        prev_text = collapse_inline_space(previous, expanded=True)
        if prev_text.endswith(" "):
            return FIRST_SPACE.sub("", text)

    return text


def is_inline_dom(node):
    if isinstance(node, str):
        return True

    if node is None:
        return False

    return False


def remove_element_edges(text, node):
    # export const removeElementEdges = (text, node) => {
    #   if (
    #     !isInline(node.parentNode) &&
    #     !node.previousSibling &&
    #     text.match(/^\s/)
    #   ) {
    #     text = text.replace(/^\s+/, '');
    #   }
    #
    #   if (text.match(/\s$/) && !node.nextSibling && !isInline(node.parentNode)) {
    #     text = text.replace(/\s$/, '');
    #   }
    #
    #   return text;
    # };
    if isinstance(node, str):
        return text

    previous = node.getprevious()
    next_ = node.getnext()
    parent = node.getparent()

    if (
        (not is_inline_dom(parent))
        and (previous is None)
        and re.match(FIRST_ANY_SPACE, text)
    ):
        text = FIRST_ALL_SPACE.sub("", text)

    if (
        re.match(ANY_SPACE_AT_END, text)
        and (next_ is None)
        and (not is_inline_dom(parent))
    ):
        text = ANY_SPACE_AT_END.sub("", text)

    return text


def collapse_inline_space(node, expanded=False):
    """See

    https://developer.mozilla.org/en-US/docs/Web/API/Document_Object_Model/Whitespace
    """
    text = node.text or ""

    if expanded:
        text = "".join(
            collapse_inline_space(n)
            for n in ([make_textnode(node.text, node)] + list(node.iterchildren()))
        )

    # 1. all spaces and tabs immediately before and after a line break are ignored
    text = remove_space_before_after_endline(text)

    # 2. Next, all tab characters are handled as space characters
    text = convert_tabs_to_spaces(text)

    # 3. Convert all line breaks to spaces
    text = convert_linebreaks_to_spaces(text)

    # 4. Any space immediately following another space
    # (even across two separate inline elements) is ignored
    text = remove_space_follow_space(text, node)

    # // 5. Sequences of spaces at the beginning and end of an element are removed
    text = remove_element_edges(text, node)

    return text


class TextNode(object):
    """Pseudo-TextNode element, mimics browser DOMParser API, where text is DOM node"""

    def __init__(self, text, parent=None, previous=None, next_=None):
        self.text = text
        self.parent = parent

        _children = list(parent.iterchildren())
        self.next_ = _children[0] if _children else None
        self.previous = previous

    def getparent(self):
        return self.parent

    def getprevious(self):
        return self.previous

    def getnext(self):
        return self.next_

    def iterchildren(self):
        return []


def make_textnode(text, node):
    parent = node.getparent()
    children = list(parent.iterchildren()) if parent is not None else [0]
    first = children[0] if children else None
    return TextNode(text, parent=node, next_=first)


class HTML2Slate(object):
    """A parser for HTML to slate conversion

    If you need to handle some custom slate markup, inherit and extend

    See https://github.com/plone/volto/blob/5f9066a70b9f3b60d462fc96a1aa7027ff9bbac0/packages/volto-slate/src/editor/deserialize.js
    """

    def to_slate(self, text):
        "Convert text to a slate value. A slate value is a list of elements"

        fragments = html5parser.fragments_fromstring(text)
        nodes = []
        for f in fragments:
            nodes += self.deserialize(f)

        return self.normalize(nodes)

    def deserialize(self, node):
        """Deserialize a node into a _list_ of slate elements"""

        if node is None:
            return []

        if isinstance(node, TextNode):
            # if is_whitespace(node):
            #     return []
            text = collapse_inline_space(node)

            return [{"text": text}] if text else None

        tagname = tag_name(node)

        handler = None

        if node.attrib.get("data-slate-data"):
            handler = self.handle_slate_data_element
        else:
            handler = getattr(self, "handle_tag_{}".format(tagname), None)
            if not handler and tagname in KNOWN_BLOCK_TYPES:
                handler = self.handle_block

        if handler:
            element = handler(node)

            if node.tail:
                text = make_textnode(node.tail, node)
                if collapse_inline_space(text):  # was clean_whitespace
                    return [element] + self.deserialize(node.tail)

            return [element]

        # fallback, "skips" the node
        return self.handle_fallback(node)

    def deserialize_children(self, node):
        """deserialize_children.

        :param node:
        """

        text = make_textnode(node.text, node)

        nodes = [text]

        for child in node.iterchildren():
            nodes.append(child)
            if child.tail:
                text = TextNode(
                    child.tail,
                    parent=child.getparent(),
                    previous=child,
                    next=child.getnext(),
                )
                nodes.append(text)
            # if is_whitespace(child.tail):
            #     nodes.append(child.tail)

        res = []
        for x in nodes:
            # if x is not None:
            res += self.deserialize(x)

        return res

    def handle_tag_a(self, node):
        """handle_tag_a.

        :param node:
        """
        attrs = node.attrib
        link = attrs.get("href", "")

        element = {"type": "a", "children": self.deserialize_children(node)}
        if link:
            if link.startswith("http") or link.startswith("//"):
                # TO DO: implement external link
                pass
            else:
                element["data"] = {
                    "link": {
                        "internal": {
                            "internal_link": [
                                {
                                    "@id": link,
                                }
                            ]
                        }
                    }
                }

        return element

    def handle_tag_br(self, node):
        """handle_tag_br.

        :param node:
        """
        return {"text": "\n"}

    def handle_block(self, node):
        """handle_block.

        :param node:
        """
        return {"type": tag_name(node), "children": self.deserialize_children(node)}

    def handle_tag_b(self, node):
        # TO DO: implement <b> special cases
        return self.handle_block(node)

    def handle_slate_data_element(self, node):
        """handle_slate_data_element.

        :param node:
        """
        element = json.loads(node.attrib["data-slate-data"])
        element["children"] = self.deserialize_children(node)
        return element

    def handle_fallback(self, node):
        "Unknown tags (for example span) are handled as pipe-through"
        return node

        # nodes = self.deserialize_children(node) + self.deserialize(node.tail)
        # return nodes

    def normalize(self, value):
        "Normalize value to match Slate constraints"

        assert isinstance(value, list)
        value = [v for v in value if v is not None]

        # all top-level elements in the value need to be block tags
        if value and [x for x in value if is_inline(value[0])]:
            value = [{"type": DEFAULT_BLOCK_TYPE, "children": value}]

        stack = deque(value)

        while stack:
            child = stack.pop()
            children = child.get("children", None)
            if children is not None:
                children = [c for c in children if c]
                # merge adjacent text nodes
                child["children"] = merge_adjacent_text_nodes(children)
                stack.extend(child["children"])

                # self._pad_with_space(child["children"])

        return value

    def _pad_with_space(self, children):
        """Mutate the children array in-place. It pads them with
        'empty spaces'.

        Extract from Slate docs:
        https://docs.slatejs.org/concepts/02-nodes#blocks-vs-inlines

        You can define which nodes are treated as inline nodes by overriding
        the editor.isInline function. (By default it always returns false.).
        Note that inline nodes cannot be the first or last child of a parent
        block, nor can it be next to another inline node in the children array.
        Slate will automatically space these with { text: '' } children by
        default with normalizeNode.

        Elements can either contain block elements or inline elements
        intermingled with text nodes as children. But elements cannot contain
        some children that are blocks and some that are inlines.
        """

        # TO DO: needs reimplementation according to above info
        if children == 0:
            children.append({"text": ""})
            return

        if not children[0].get("text"):
            children.insert(0, {"text": ""})
        if not children[-1].get("text"):
            children.append({"text": ""})


def text_to_slate(text):
    """text_to_slate.

    :param text:
    """
    return HTML2Slate().to_slate(text)


# def is_whitespace(text):
#     """Returns true if the text is only whitespace characters"""
#
#     # TODO: rewrite using mozila code
#
#     if not isinstance(text, str):
#         return False
#
#     return len(re.sub(r"\s|\t|\n", "", text)) == 0
# export const isInline = (node) =>
#   node &&
#   (node.nodeType === TEXT_NODE || INLINE_ELEMENTS.includes(node.nodeName));
