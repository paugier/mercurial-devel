from i18n import _
from mercurial import util
import templatekw

def tolist(val):
    """
    a convenience method to return an empty list instead of None
    """
    if val is None:
        return []
    else:
        return [val]

class namespaces(object):
    """provides an interface to register and operate on multiple namespaces. See
    the namespace class below for details on the namespace object.

    """

    _names_version = 0

    def __init__(self):
        self._names = util.sortdict()

        # we need current mercurial named objects (bookmarks, tags, and
        # branches) to be initialized somewhere, so that place is here
        bmknames = lambda repo: repo._bookmarks.keys()
        bmknamemap = lambda repo, name: tolist(repo._bookmarks.get(name))
        bmknodemap = lambda repo, name: repo.nodebookmarks(name)
        n = namespace("bookmarks", templatename="bookmark", listnames=bmknames,
                      namemap=bmknamemap, nodemap=bmknodemap)
        self.addnamespace(n)

        tagnames = lambda repo: [t for t, n in repo.tagslist()]
        tagnamemap = lambda repo, name: tolist(repo._tagscache.tags.get(name))
        tagnodemap = lambda repo, name: repo.nodetags(name)
        n = namespace("tags", templatename="tag", listnames=tagnames,
                      namemap=tagnamemap, nodemap=tagnodemap)
        self.addnamespace(n)

        bnames = lambda repo: repo.branchmap().keys()
        bnamemap = lambda repo, name: tolist(repo.branchtip(name, True))
        bnodemap = lambda repo, node: [repo[node].branch()]
        n = namespace("branches", templatename="branch", listnames=bnames,
                      namemap=bnamemap, nodemap=bnodemap)
        self.addnamespace(n)

    def __getitem__(self, namespace):
        """returns the namespace object"""
        return self._names[namespace]

    def __iter__(self):
        return self._names.__iter__()

    def iteritems(self):
        return self._names.iteritems()

    def addnamespace(self, namespace, order=None):
        """register a namespace

        namespace: the name to be registered (in plural form)
        order: optional argument to specify the order of namespaces
               (e.g. 'branches' should be listed before 'bookmarks')

        """
        if order is not None:
            self._names.insert(order, namespace.name, namespace)
        else:
            self._names[namespace.name] = namespace

        # we only generate a template keyword if one does not already exist
        if namespace.name not in templatekw.keywords:
            def generatekw(**args):
                return templatekw.shownames(namespace.name, **args)

            templatekw.keywords[namespace.name] = generatekw

    def singlenode(self, repo, name):
        """
        Return the 'best' node for the given name. Best means the first node
        in the first nonempty list returned by a name-to-nodes mapping function
        in the defined precedence order.

        Raises a KeyError if there is no such node.
        """
        for ns, v in self._names.iteritems():
            n = v.namemap(repo, name)
            if n:
                # return max revision number
                if len(n) > 1:
                    cl = repo.changelog
                    maxrev = max(cl.rev(node) for node in n)
                    return cl.node(maxrev)
                return n[0]
        raise KeyError(_('no such name: %s') % name)

class namespace(object):
    """provides an interface to a namespace

    Namespaces are basically generic many-to-many mapping between some
    (namespaced) names and nodes. The goal here is to control the pollution of
    jamming things into tags or bookmarks (in extension-land) and to simplify
    internal bits of mercurial: log output, tab completion, etc.

    More precisely, we define a mapping of names to nodes, and a mapping from
    nodes to names. Each mapping returns a list.

    Furthermore, each name mapping will be passed a name to lookup which might
    not be in its domain. In this case, each method should return an empty list
    and not raise an error.

    This namespace object will define the properties we need:
      'name': the namespace (plural form)
      'templatename': name to use for templating (usually the singular form
                      of the plural namespace name)
      'listnames': list of all names in the namespace (usually the keys of a
                   dictionary)
      'namemap': function that takes a name and returns a list of nodes
      'nodemap': function that takes a node and returns a list of names

    """

    def __init__(self, name, templatename=None, logname=None, listnames=None,
                 namemap=None, nodemap=None):
        """create a namespace

        name: the namespace to be registered (in plural form)
        templatename: the name to use for templating
        logname: the name to use for log output; if not specified templatename
                 is used
        listnames: function to list all names
        namemap: function that inputs a node, output name(s)
        nodemap: function that inputs a name, output node(s)

        """
        self.name = name
        self.templatename = templatename
        self.logname = logname
        self.listnames = listnames
        self.namemap = namemap
        self.nodemap = nodemap

        # if logname is not specified, use the template name as backup
        if self.logname is None:
            self.logname = self.templatename

    def names(self, repo, node):
        """method that returns a (sorted) list of names in a namespace that
        match a given node"""
        return sorted(self.nodemap(repo, node))

    def nodes(self, repo, name):
        """method that returns a list of nodes in a namespace that
        match a given name.

        """
        return sorted(self.namemap(repo, name))
