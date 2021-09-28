/*
 parsers.c - efficient content parsing

 Copyright 2008 Olivia Mackall <olivia@selenic.com> and others

 This software may be used and distributed according to the terms of
 the GNU General Public License, incorporated herein by reference.
*/

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <ctype.h>
#include <stddef.h>
#include <string.h>

#include "bitmanipulation.h"
#include "charencode.h"
#include "util.h"

#ifdef IS_PY3K
/* The mapping of Python types is meant to be temporary to get Python
 * 3 to compile. We should remove this once Python 3 support is fully
 * supported and proper types are used in the extensions themselves. */
#define PyInt_Check PyLong_Check
#define PyInt_FromLong PyLong_FromLong
#define PyInt_FromSsize_t PyLong_FromSsize_t
#define PyInt_AsLong PyLong_AsLong
#endif

static const char *const versionerrortext = "Python minor version mismatch";

static const int dirstate_v1_from_p2 = -2;
static const int dirstate_v1_nonnormal = -1;
static const int ambiguous_time = -1;

static PyObject *dict_new_presized(PyObject *self, PyObject *args)
{
	Py_ssize_t expected_size;

	if (!PyArg_ParseTuple(args, "n:make_presized_dict", &expected_size)) {
		return NULL;
	}

	return _dict_new_presized(expected_size);
}

static PyObject *dirstate_item_new(PyTypeObject *subtype, PyObject *args,
                                   PyObject *kwds)
{
	/* We do all the initialization here and not a tp_init function because
	 * dirstate_item is immutable. */
	dirstateItemObject *t;
	int wc_tracked;
	int p1_tracked;
	int p2_tracked;
	int merged;
	int clean_p1;
	int clean_p2;
	int possibly_dirty;
	PyObject *parentfiledata;
	static char *keywords_name[] = {
	    "wc_tracked",     "p1_tracked",     "p2_tracked",
	    "merged",         "clean_p1",       "clean_p2",
	    "possibly_dirty", "parentfiledata", NULL,
	};
	wc_tracked = 0;
	p1_tracked = 0;
	p2_tracked = 0;
	merged = 0;
	clean_p1 = 0;
	clean_p2 = 0;
	possibly_dirty = 0;
	parentfiledata = Py_None;
	if (!PyArg_ParseTupleAndKeywords(args, kwds, "iiiiiiiO", keywords_name,
	                                 &wc_tracked, &p1_tracked, &p2_tracked,
	                                 &merged, &clean_p1, &clean_p2,
	                                 &possibly_dirty, &parentfiledata

	                                 )) {
		return NULL;
	}
	if (merged && (clean_p1 || clean_p2)) {
		PyErr_SetString(PyExc_RuntimeError,
		                "`merged` argument incompatible with "
		                "`clean_p1`/`clean_p2`");
		return NULL;
	}
	t = (dirstateItemObject *)subtype->tp_alloc(subtype, 1);
	if (!t) {
		return NULL;
	}

	t->flags = 0;
	if (wc_tracked) {
		t->flags |= dirstate_flag_wc_tracked;
	}
	if (p1_tracked) {
		t->flags |= dirstate_flag_p1_tracked;
	}
	if (p2_tracked) {
		t->flags |= dirstate_flag_p2_tracked;
	}
	if (possibly_dirty) {
		t->flags |= dirstate_flag_possibly_dirty;
	}
	if (merged) {
		t->flags |= dirstate_flag_merged;
	}
	if (clean_p1) {
		t->flags |= dirstate_flag_clean_p1;
	}
	if (clean_p2) {
		t->flags |= dirstate_flag_clean_p2;
	}
	t->mode = 0;
	t->size = dirstate_v1_nonnormal;
	t->mtime = ambiguous_time;
	if (parentfiledata != Py_None) {
		if (!PyTuple_CheckExact(parentfiledata)) {
			PyErr_SetString(
			    PyExc_TypeError,
			    "parentfiledata should be a Tuple or None");
			return NULL;
		}
		t->mode =
		    (int)PyLong_AsLong(PyTuple_GetItem(parentfiledata, 0));
		t->size =
		    (int)PyLong_AsLong(PyTuple_GetItem(parentfiledata, 1));
		t->mtime =
		    (int)PyLong_AsLong(PyTuple_GetItem(parentfiledata, 2));
	}
	return (PyObject *)t;
}

static void dirstate_item_dealloc(PyObject *o)
{
	PyObject_Del(o);
}

static inline bool dirstate_item_c_tracked(dirstateItemObject *self)
{
	return (self->flags & dirstate_flag_wc_tracked);
}

static inline bool dirstate_item_c_added(dirstateItemObject *self)
{
	unsigned char mask =
	    (dirstate_flag_wc_tracked | dirstate_flag_p1_tracked |
	     dirstate_flag_p2_tracked);
	unsigned char target = dirstate_flag_wc_tracked;
	return (self->flags & mask) == target;
}

static inline bool dirstate_item_c_removed(dirstateItemObject *self)
{
	if (self->flags & dirstate_flag_wc_tracked) {
		return false;
	}
	return (self->flags &
	        (dirstate_flag_p1_tracked | dirstate_flag_p2_tracked));
}

static inline bool dirstate_item_c_merged(dirstateItemObject *self)
{
	return ((self->flags & dirstate_flag_wc_tracked) &&
	        (self->flags & dirstate_flag_merged));
}

static inline bool dirstate_item_c_merged_removed(dirstateItemObject *self)
{
	if (!dirstate_item_c_removed(self)) {
		return false;
	}
	return (self->flags & dirstate_flag_merged);
}

static inline bool dirstate_item_c_from_p2(dirstateItemObject *self)
{
	if (!dirstate_item_c_tracked(self)) {
		return false;
	}
	return (self->flags & dirstate_flag_clean_p2);
}

static inline bool dirstate_item_c_from_p2_removed(dirstateItemObject *self)
{
	if (!dirstate_item_c_removed(self)) {
		return false;
	}
	return (self->flags & dirstate_flag_clean_p2);
}

static inline char dirstate_item_c_v1_state(dirstateItemObject *self)
{
	if (dirstate_item_c_removed(self)) {
		return 'r';
	} else if (dirstate_item_c_merged(self)) {
		return 'm';
	} else if (dirstate_item_c_added(self)) {
		return 'a';
	} else {
		return 'n';
	}
}

static inline int dirstate_item_c_v1_mode(dirstateItemObject *self)
{
	return self->mode;
}

static inline int dirstate_item_c_v1_size(dirstateItemObject *self)
{
	if (dirstate_item_c_merged_removed(self)) {
		return dirstate_v1_nonnormal;
	} else if (dirstate_item_c_from_p2_removed(self)) {
		return dirstate_v1_from_p2;
	} else if (dirstate_item_c_removed(self)) {
		return 0;
	} else if (dirstate_item_c_merged(self)) {
		return dirstate_v1_from_p2;
	} else if (dirstate_item_c_added(self)) {
		return dirstate_v1_nonnormal;
	} else if (dirstate_item_c_from_p2(self)) {
		return dirstate_v1_from_p2;
	} else if (self->flags & dirstate_flag_possibly_dirty) {
		return self->size; /* NON NORMAL ? */
	} else {
		return self->size;
	}
}

static inline int dirstate_item_c_v1_mtime(dirstateItemObject *self)
{
	if (dirstate_item_c_removed(self)) {
		return 0;
	} else if (self->flags & dirstate_flag_possibly_dirty) {
		return ambiguous_time;
	} else if (dirstate_item_c_merged(self)) {
		return ambiguous_time;
	} else if (dirstate_item_c_added(self)) {
		return ambiguous_time;
	} else if (dirstate_item_c_from_p2(self)) {
		return ambiguous_time;
	} else {
		return self->mtime;
	}
}

static PyObject *dirstate_item_v1_state(dirstateItemObject *self)
{
	char state = dirstate_item_c_v1_state(self);
	return PyBytes_FromStringAndSize(&state, 1);
};

static PyObject *dirstate_item_v1_mode(dirstateItemObject *self)
{
	return PyInt_FromLong(dirstate_item_c_v1_mode(self));
};

static PyObject *dirstate_item_v1_size(dirstateItemObject *self)
{
	return PyInt_FromLong(dirstate_item_c_v1_size(self));
};

static PyObject *dirstate_item_v1_mtime(dirstateItemObject *self)
{
	return PyInt_FromLong(dirstate_item_c_v1_mtime(self));
};

static PyObject *dirstate_item_need_delay(dirstateItemObject *self,
                                          PyObject *value)
{
	long now;
	if (!pylong_to_long(value, &now)) {
		return NULL;
	}
	if (dirstate_item_c_v1_state(self) == 'n' &&
	    dirstate_item_c_v1_mtime(self) == now) {
		Py_RETURN_TRUE;
	} else {
		Py_RETURN_FALSE;
	}
};

/* This will never change since it's bound to V1
 */
static inline dirstateItemObject *
dirstate_item_from_v1_data(char state, int mode, int size, int mtime)
{
	dirstateItemObject *t =
	    PyObject_New(dirstateItemObject, &dirstateItemType);
	if (!t) {
		return NULL;
	}

	if (state == 'm') {
		t->flags =
		    (dirstate_flag_wc_tracked | dirstate_flag_p1_tracked |
		     dirstate_flag_p2_tracked | dirstate_flag_merged);
		t->mode = 0;
		t->size = dirstate_v1_from_p2;
		t->mtime = ambiguous_time;
	} else if (state == 'a') {
		t->flags = dirstate_flag_wc_tracked;
		t->mode = 0;
		t->size = dirstate_v1_nonnormal;
		t->mtime = ambiguous_time;
	} else if (state == 'r') {
		t->mode = 0;
		t->size = 0;
		t->mtime = 0;
		if (size == dirstate_v1_nonnormal) {
			t->flags =
			    (dirstate_flag_p1_tracked |
			     dirstate_flag_p2_tracked | dirstate_flag_merged);
		} else if (size == dirstate_v1_from_p2) {
			t->flags =
			    (dirstate_flag_p2_tracked | dirstate_flag_clean_p2);
		} else {
			t->flags = dirstate_flag_p1_tracked;
		}
	} else if (state == 'n') {
		if (size == dirstate_v1_from_p2) {
			t->flags =
			    (dirstate_flag_wc_tracked |
			     dirstate_flag_p2_tracked | dirstate_flag_clean_p2);
			t->mode = 0;
			t->size = dirstate_v1_from_p2;
			t->mtime = ambiguous_time;
		} else if (size == dirstate_v1_nonnormal) {
			t->flags = (dirstate_flag_wc_tracked |
			            dirstate_flag_p1_tracked |
			            dirstate_flag_possibly_dirty);
			t->mode = 0;
			t->size = dirstate_v1_nonnormal;
			t->mtime = ambiguous_time;
		} else if (mtime == ambiguous_time) {
			t->flags = (dirstate_flag_wc_tracked |
			            dirstate_flag_p1_tracked |
			            dirstate_flag_possibly_dirty);
			t->mode = mode;
			t->size = size;
			t->mtime = 0;
		} else {
			t->flags = (dirstate_flag_wc_tracked |
			            dirstate_flag_p1_tracked);
			t->mode = mode;
			t->size = size;
			t->mtime = mtime;
		}
	} else {
		PyErr_Format(PyExc_RuntimeError,
		             "unknown state: `%c` (%d, %d, %d)", state, mode,
		             size, mtime, NULL);
		Py_DECREF(t);
		return NULL;
	}

	return t;
}

/* This will never change since it's bound to V1, unlike `dirstate_item_new` */
static PyObject *dirstate_item_from_v1_meth(PyTypeObject *subtype,
                                            PyObject *args)
{
	/* We do all the initialization here and not a tp_init function because
	 * dirstate_item is immutable. */
	char state;
	int size, mode, mtime;
	if (!PyArg_ParseTuple(args, "ciii", &state, &mode, &size, &mtime)) {
		return NULL;
	}
	return (PyObject *)dirstate_item_from_v1_data(state, mode, size, mtime);
};

/* constructor to help legacy API to build a new "added" item

Should eventually be removed */
static PyObject *dirstate_item_new_added(PyTypeObject *subtype)
{
	dirstateItemObject *t;
	t = (dirstateItemObject *)subtype->tp_alloc(subtype, 1);
	if (!t) {
		return NULL;
	}
	t->flags = dirstate_flag_wc_tracked;
	t->mode = 0;
	t->size = dirstate_v1_nonnormal;
	t->mtime = ambiguous_time;
	return (PyObject *)t;
};

/* constructor to help legacy API to build a new "merged" item

Should eventually be removed */
static PyObject *dirstate_item_new_merged(PyTypeObject *subtype)
{
	dirstateItemObject *t;
	t = (dirstateItemObject *)subtype->tp_alloc(subtype, 1);
	if (!t) {
		return NULL;
	}
	t->flags = (dirstate_flag_wc_tracked | dirstate_flag_p1_tracked |
	            dirstate_flag_p2_tracked | dirstate_flag_merged);
	t->mode = 0;
	t->size = dirstate_v1_from_p2;
	t->mtime = ambiguous_time;
	return (PyObject *)t;
};

/* constructor to help legacy API to build a new "from_p2" item

Should eventually be removed */
static PyObject *dirstate_item_new_from_p2(PyTypeObject *subtype)
{
	/* We do all the initialization here and not a tp_init function because
	 * dirstate_item is immutable. */
	dirstateItemObject *t;
	t = (dirstateItemObject *)subtype->tp_alloc(subtype, 1);
	if (!t) {
		return NULL;
	}
	t->flags = (dirstate_flag_wc_tracked | dirstate_flag_p2_tracked |
	            dirstate_flag_clean_p2);
	t->mode = 0;
	t->size = dirstate_v1_from_p2;
	t->mtime = ambiguous_time;
	return (PyObject *)t;
};

/* constructor to help legacy API to build a new "possibly" item

Should eventually be removed */
static PyObject *dirstate_item_new_possibly_dirty(PyTypeObject *subtype)
{
	/* We do all the initialization here and not a tp_init function because
	 * dirstate_item is immutable. */
	dirstateItemObject *t;
	t = (dirstateItemObject *)subtype->tp_alloc(subtype, 1);
	if (!t) {
		return NULL;
	}
	t->flags = (dirstate_flag_wc_tracked | dirstate_flag_p1_tracked |
	            dirstate_flag_possibly_dirty);
	t->mode = 0;
	t->size = dirstate_v1_nonnormal;
	t->mtime = ambiguous_time;
	return (PyObject *)t;
};

/* constructor to help legacy API to build a new "normal" item

Should eventually be removed */
static PyObject *dirstate_item_new_normal(PyTypeObject *subtype, PyObject *args)
{
	/* We do all the initialization here and not a tp_init function because
	 * dirstate_item is immutable. */
	dirstateItemObject *t;
	int size, mode, mtime;
	if (!PyArg_ParseTuple(args, "iii", &mode, &size, &mtime)) {
		return NULL;
	}

	t = (dirstateItemObject *)subtype->tp_alloc(subtype, 1);
	if (!t) {
		return NULL;
	}
	t->flags = (dirstate_flag_wc_tracked | dirstate_flag_p1_tracked);
	t->mode = mode;
	t->size = size;
	t->mtime = mtime;
	return (PyObject *)t;
};

/* This means the next status call will have to actually check its content
   to make sure it is correct. */
static PyObject *dirstate_item_set_possibly_dirty(dirstateItemObject *self)
{
	self->flags |= dirstate_flag_possibly_dirty;
	Py_RETURN_NONE;
}

/* See docstring of the python implementation for details */
static PyObject *dirstate_item_set_clean(dirstateItemObject *self,
                                         PyObject *args)
{
	int size, mode, mtime;
	if (!PyArg_ParseTuple(args, "iii", &mode, &size, &mtime)) {
		return NULL;
	}
	self->flags = dirstate_flag_wc_tracked | dirstate_flag_p1_tracked;
	self->mode = mode;
	self->size = size;
	self->mtime = mtime;
	Py_RETURN_NONE;
}

static PyObject *dirstate_item_set_tracked(dirstateItemObject *self)
{
	self->flags |= dirstate_flag_wc_tracked;
	self->flags |= dirstate_flag_possibly_dirty;
	/* size = None on the python size turn into size = NON_NORMAL when
	 * accessed. So the next line is currently required, but a some future
	 * clean up would be welcome. */
	self->size = dirstate_v1_nonnormal;
	Py_RETURN_NONE;
}

static PyObject *dirstate_item_set_untracked(dirstateItemObject *self)
{
	self->flags &= ~dirstate_flag_wc_tracked;
	self->mode = 0;
	self->mtime = 0;
	self->size = 0;
	Py_RETURN_NONE;
}

static PyObject *dirstate_item_drop_merge_data(dirstateItemObject *self)
{
	if (dirstate_item_c_merged(self) || dirstate_item_c_from_p2(self)) {
		if (dirstate_item_c_merged(self)) {
			self->flags |= dirstate_flag_p1_tracked;
		} else {
			self->flags &= ~dirstate_flag_p1_tracked;
		}
		self->flags &=
		    ~(dirstate_flag_merged | dirstate_flag_clean_p1 |
		      dirstate_flag_clean_p2 | dirstate_flag_p2_tracked);
		self->flags |= dirstate_flag_possibly_dirty;
		self->mode = 0;
		self->mtime = 0;
		/* size = None on the python size turn into size = NON_NORMAL
		 * when accessed. So the next line is currently required, but a
		 * some future clean up would be welcome. */
		self->size = dirstate_v1_nonnormal;
	}
	Py_RETURN_NONE;
}
static PyMethodDef dirstate_item_methods[] = {
    {"v1_state", (PyCFunction)dirstate_item_v1_state, METH_NOARGS,
     "return a \"state\" suitable for v1 serialization"},
    {"v1_mode", (PyCFunction)dirstate_item_v1_mode, METH_NOARGS,
     "return a \"mode\" suitable for v1 serialization"},
    {"v1_size", (PyCFunction)dirstate_item_v1_size, METH_NOARGS,
     "return a \"size\" suitable for v1 serialization"},
    {"v1_mtime", (PyCFunction)dirstate_item_v1_mtime, METH_NOARGS,
     "return a \"mtime\" suitable for v1 serialization"},
    {"need_delay", (PyCFunction)dirstate_item_need_delay, METH_O,
     "True if the stored mtime would be ambiguous with the current time"},
    {"from_v1_data", (PyCFunction)dirstate_item_from_v1_meth,
     METH_VARARGS | METH_CLASS, "build a new DirstateItem object from V1 data"},
    {"new_added", (PyCFunction)dirstate_item_new_added,
     METH_NOARGS | METH_CLASS,
     "constructor to help legacy API to build a new \"added\" item"},
    {"new_merged", (PyCFunction)dirstate_item_new_merged,
     METH_NOARGS | METH_CLASS,
     "constructor to help legacy API to build a new \"merged\" item"},
    {"new_from_p2", (PyCFunction)dirstate_item_new_from_p2,
     METH_NOARGS | METH_CLASS,
     "constructor to help legacy API to build a new \"from_p2\" item"},
    {"new_possibly_dirty", (PyCFunction)dirstate_item_new_possibly_dirty,
     METH_NOARGS | METH_CLASS,
     "constructor to help legacy API to build a new \"possibly_dirty\" item"},
    {"new_normal", (PyCFunction)dirstate_item_new_normal,
     METH_VARARGS | METH_CLASS,
     "constructor to help legacy API to build a new \"normal\" item"},
    {"set_possibly_dirty", (PyCFunction)dirstate_item_set_possibly_dirty,
     METH_NOARGS, "mark a file as \"possibly dirty\""},
    {"set_clean", (PyCFunction)dirstate_item_set_clean, METH_VARARGS,
     "mark a file as \"clean\""},
    {"set_tracked", (PyCFunction)dirstate_item_set_tracked, METH_NOARGS,
     "mark a file as \"tracked\""},
    {"set_untracked", (PyCFunction)dirstate_item_set_untracked, METH_NOARGS,
     "mark a file as \"untracked\""},
    {"drop_merge_data", (PyCFunction)dirstate_item_drop_merge_data, METH_NOARGS,
     "remove all \"merge-only\" from a DirstateItem"},
    {NULL} /* Sentinel */
};

static PyObject *dirstate_item_get_mode(dirstateItemObject *self)
{
	return PyInt_FromLong(dirstate_item_c_v1_mode(self));
};

static PyObject *dirstate_item_get_size(dirstateItemObject *self)
{
	return PyInt_FromLong(dirstate_item_c_v1_size(self));
};

static PyObject *dirstate_item_get_mtime(dirstateItemObject *self)
{
	return PyInt_FromLong(dirstate_item_c_v1_mtime(self));
};

static PyObject *dirstate_item_get_state(dirstateItemObject *self)
{
	char state = dirstate_item_c_v1_state(self);
	return PyBytes_FromStringAndSize(&state, 1);
};

static PyObject *dirstate_item_get_tracked(dirstateItemObject *self)
{
	if (dirstate_item_c_tracked(self)) {
		Py_RETURN_TRUE;
	} else {
		Py_RETURN_FALSE;
	}
};

static PyObject *dirstate_item_get_added(dirstateItemObject *self)
{
	if (dirstate_item_c_added(self)) {
		Py_RETURN_TRUE;
	} else {
		Py_RETURN_FALSE;
	}
};

static PyObject *dirstate_item_get_merged(dirstateItemObject *self)
{
	if (dirstate_item_c_merged(self)) {
		Py_RETURN_TRUE;
	} else {
		Py_RETURN_FALSE;
	}
};

static PyObject *dirstate_item_get_merged_removed(dirstateItemObject *self)
{
	if (dirstate_item_c_merged_removed(self)) {
		Py_RETURN_TRUE;
	} else {
		Py_RETURN_FALSE;
	}
};

static PyObject *dirstate_item_get_from_p2(dirstateItemObject *self)
{
	if (dirstate_item_c_from_p2(self)) {
		Py_RETURN_TRUE;
	} else {
		Py_RETURN_FALSE;
	}
};

static PyObject *dirstate_item_get_from_p2_removed(dirstateItemObject *self)
{
	if (dirstate_item_c_from_p2_removed(self)) {
		Py_RETURN_TRUE;
	} else {
		Py_RETURN_FALSE;
	}
};

static PyObject *dirstate_item_get_removed(dirstateItemObject *self)
{
	if (dirstate_item_c_removed(self)) {
		Py_RETURN_TRUE;
	} else {
		Py_RETURN_FALSE;
	}
};

static PyGetSetDef dirstate_item_getset[] = {
    {"mode", (getter)dirstate_item_get_mode, NULL, "mode", NULL},
    {"size", (getter)dirstate_item_get_size, NULL, "size", NULL},
    {"mtime", (getter)dirstate_item_get_mtime, NULL, "mtime", NULL},
    {"state", (getter)dirstate_item_get_state, NULL, "state", NULL},
    {"tracked", (getter)dirstate_item_get_tracked, NULL, "tracked", NULL},
    {"added", (getter)dirstate_item_get_added, NULL, "added", NULL},
    {"merged_removed", (getter)dirstate_item_get_merged_removed, NULL,
     "merged_removed", NULL},
    {"merged", (getter)dirstate_item_get_merged, NULL, "merged", NULL},
    {"from_p2_removed", (getter)dirstate_item_get_from_p2_removed, NULL,
     "from_p2_removed", NULL},
    {"from_p2", (getter)dirstate_item_get_from_p2, NULL, "from_p2", NULL},
    {"removed", (getter)dirstate_item_get_removed, NULL, "removed", NULL},
    {NULL} /* Sentinel */
};

PyTypeObject dirstateItemType = {
    PyVarObject_HEAD_INIT(NULL, 0)     /* header */
    "dirstate_tuple",                  /* tp_name */
    sizeof(dirstateItemObject),        /* tp_basicsize */
    0,                                 /* tp_itemsize */
    (destructor)dirstate_item_dealloc, /* tp_dealloc */
    0,                                 /* tp_print */
    0,                                 /* tp_getattr */
    0,                                 /* tp_setattr */
    0,                                 /* tp_compare */
    0,                                 /* tp_repr */
    0,                                 /* tp_as_number */
    0,                                 /* tp_as_sequence */
    0,                                 /* tp_as_mapping */
    0,                                 /* tp_hash  */
    0,                                 /* tp_call */
    0,                                 /* tp_str */
    0,                                 /* tp_getattro */
    0,                                 /* tp_setattro */
    0,                                 /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,                /* tp_flags */
    "dirstate tuple",                  /* tp_doc */
    0,                                 /* tp_traverse */
    0,                                 /* tp_clear */
    0,                                 /* tp_richcompare */
    0,                                 /* tp_weaklistoffset */
    0,                                 /* tp_iter */
    0,                                 /* tp_iternext */
    dirstate_item_methods,             /* tp_methods */
    0,                                 /* tp_members */
    dirstate_item_getset,              /* tp_getset */
    0,                                 /* tp_base */
    0,                                 /* tp_dict */
    0,                                 /* tp_descr_get */
    0,                                 /* tp_descr_set */
    0,                                 /* tp_dictoffset */
    0,                                 /* tp_init */
    0,                                 /* tp_alloc */
    dirstate_item_new,                 /* tp_new */
};

static PyObject *parse_dirstate(PyObject *self, PyObject *args)
{
	PyObject *dmap, *cmap, *parents = NULL, *ret = NULL;
	PyObject *fname = NULL, *cname = NULL, *entry = NULL;
	char state, *cur, *str, *cpos;
	int mode, size, mtime;
	unsigned int flen, pos = 40;
	Py_ssize_t len = 40;
	Py_ssize_t readlen;

	if (!PyArg_ParseTuple(
	        args, PY23("O!O!s#:parse_dirstate", "O!O!y#:parse_dirstate"),
	        &PyDict_Type, &dmap, &PyDict_Type, &cmap, &str, &readlen)) {
		goto quit;
	}

	len = readlen;

	/* read parents */
	if (len < 40) {
		PyErr_SetString(PyExc_ValueError,
		                "too little data for parents");
		goto quit;
	}

	parents = Py_BuildValue(PY23("s#s#", "y#y#"), str, (Py_ssize_t)20,
	                        str + 20, (Py_ssize_t)20);
	if (!parents) {
		goto quit;
	}

	/* read filenames */
	while (pos >= 40 && pos < len) {
		if (pos + 17 > len) {
			PyErr_SetString(PyExc_ValueError,
			                "overflow in dirstate");
			goto quit;
		}
		cur = str + pos;
		/* unpack header */
		state = *cur;
		mode = getbe32(cur + 1);
		size = getbe32(cur + 5);
		mtime = getbe32(cur + 9);
		flen = getbe32(cur + 13);
		pos += 17;
		cur += 17;
		if (flen > len - pos) {
			PyErr_SetString(PyExc_ValueError,
			                "overflow in dirstate");
			goto quit;
		}

		entry = (PyObject *)dirstate_item_from_v1_data(state, mode,
		                                               size, mtime);
		if (!entry)
			goto quit;
		cpos = memchr(cur, 0, flen);
		if (cpos) {
			fname = PyBytes_FromStringAndSize(cur, cpos - cur);
			cname = PyBytes_FromStringAndSize(
			    cpos + 1, flen - (cpos - cur) - 1);
			if (!fname || !cname ||
			    PyDict_SetItem(cmap, fname, cname) == -1 ||
			    PyDict_SetItem(dmap, fname, entry) == -1) {
				goto quit;
			}
			Py_DECREF(cname);
		} else {
			fname = PyBytes_FromStringAndSize(cur, flen);
			if (!fname ||
			    PyDict_SetItem(dmap, fname, entry) == -1) {
				goto quit;
			}
		}
		Py_DECREF(fname);
		Py_DECREF(entry);
		fname = cname = entry = NULL;
		pos += flen;
	}

	ret = parents;
	Py_INCREF(ret);
quit:
	Py_XDECREF(fname);
	Py_XDECREF(cname);
	Py_XDECREF(entry);
	Py_XDECREF(parents);
	return ret;
}

/*
 * Efficiently pack a dirstate object into its on-disk format.
 */
static PyObject *pack_dirstate(PyObject *self, PyObject *args)
{
	PyObject *packobj = NULL;
	PyObject *map, *copymap, *pl, *mtime_unset = NULL;
	Py_ssize_t nbytes, pos, l;
	PyObject *k, *v = NULL, *pn;
	char *p, *s;
	int now;

	if (!PyArg_ParseTuple(args, "O!O!O!i:pack_dirstate", &PyDict_Type, &map,
	                      &PyDict_Type, &copymap, &PyTuple_Type, &pl,
	                      &now)) {
		return NULL;
	}

	if (PyTuple_Size(pl) != 2) {
		PyErr_SetString(PyExc_TypeError, "expected 2-element tuple");
		return NULL;
	}

	/* Figure out how much we need to allocate. */
	for (nbytes = 40, pos = 0; PyDict_Next(map, &pos, &k, &v);) {
		PyObject *c;
		if (!PyBytes_Check(k)) {
			PyErr_SetString(PyExc_TypeError, "expected string key");
			goto bail;
		}
		nbytes += PyBytes_GET_SIZE(k) + 17;
		c = PyDict_GetItem(copymap, k);
		if (c) {
			if (!PyBytes_Check(c)) {
				PyErr_SetString(PyExc_TypeError,
				                "expected string key");
				goto bail;
			}
			nbytes += PyBytes_GET_SIZE(c) + 1;
		}
	}

	packobj = PyBytes_FromStringAndSize(NULL, nbytes);
	if (packobj == NULL) {
		goto bail;
	}

	p = PyBytes_AS_STRING(packobj);

	pn = PyTuple_GET_ITEM(pl, 0);
	if (PyBytes_AsStringAndSize(pn, &s, &l) == -1 || l != 20) {
		PyErr_SetString(PyExc_TypeError, "expected a 20-byte hash");
		goto bail;
	}
	memcpy(p, s, l);
	p += 20;
	pn = PyTuple_GET_ITEM(pl, 1);
	if (PyBytes_AsStringAndSize(pn, &s, &l) == -1 || l != 20) {
		PyErr_SetString(PyExc_TypeError, "expected a 20-byte hash");
		goto bail;
	}
	memcpy(p, s, l);
	p += 20;

	for (pos = 0; PyDict_Next(map, &pos, &k, &v);) {
		dirstateItemObject *tuple;
		char state;
		int mode, size, mtime;
		Py_ssize_t len, l;
		PyObject *o;
		char *t;

		if (!dirstate_tuple_check(v)) {
			PyErr_SetString(PyExc_TypeError,
			                "expected a dirstate tuple");
			goto bail;
		}
		tuple = (dirstateItemObject *)v;

		state = dirstate_item_c_v1_state(tuple);
		mode = dirstate_item_c_v1_mode(tuple);
		size = dirstate_item_c_v1_size(tuple);
		mtime = dirstate_item_c_v1_mtime(tuple);
		if (state == 'n' && mtime == now) {
			/* See pure/parsers.py:pack_dirstate for why we do
			 * this. */
			mtime = -1;
			mtime_unset = (PyObject *)dirstate_item_from_v1_data(
			    state, mode, size, mtime);
			if (!mtime_unset) {
				goto bail;
			}
			if (PyDict_SetItem(map, k, mtime_unset) == -1) {
				goto bail;
			}
			Py_DECREF(mtime_unset);
			mtime_unset = NULL;
		}
		*p++ = state;
		putbe32((uint32_t)mode, p);
		putbe32((uint32_t)size, p + 4);
		putbe32((uint32_t)mtime, p + 8);
		t = p + 12;
		p += 16;
		len = PyBytes_GET_SIZE(k);
		memcpy(p, PyBytes_AS_STRING(k), len);
		p += len;
		o = PyDict_GetItem(copymap, k);
		if (o) {
			*p++ = '\0';
			l = PyBytes_GET_SIZE(o);
			memcpy(p, PyBytes_AS_STRING(o), l);
			p += l;
			len += l + 1;
		}
		putbe32((uint32_t)len, t);
	}

	pos = p - PyBytes_AS_STRING(packobj);
	if (pos != nbytes) {
		PyErr_Format(PyExc_SystemError, "bad dirstate size: %ld != %ld",
		             (long)pos, (long)nbytes);
		goto bail;
	}

	return packobj;
bail:
	Py_XDECREF(mtime_unset);
	Py_XDECREF(packobj);
	Py_XDECREF(v);
	return NULL;
}

#define BUMPED_FIX 1
#define USING_SHA_256 2
#define FM1_HEADER_SIZE (4 + 8 + 2 + 2 + 1 + 1 + 1)

static PyObject *readshas(const char *source, unsigned char num,
                          Py_ssize_t hashwidth)
{
	int i;
	PyObject *list = PyTuple_New(num);
	if (list == NULL) {
		return NULL;
	}
	for (i = 0; i < num; i++) {
		PyObject *hash = PyBytes_FromStringAndSize(source, hashwidth);
		if (hash == NULL) {
			Py_DECREF(list);
			return NULL;
		}
		PyTuple_SET_ITEM(list, i, hash);
		source += hashwidth;
	}
	return list;
}

static PyObject *fm1readmarker(const char *databegin, const char *dataend,
                               uint32_t *msize)
{
	const char *data = databegin;
	const char *meta;

	double mtime;
	int16_t tz;
	uint16_t flags;
	unsigned char nsuccs, nparents, nmetadata;
	Py_ssize_t hashwidth = 20;

	PyObject *prec = NULL, *parents = NULL, *succs = NULL;
	PyObject *metadata = NULL, *ret = NULL;
	int i;

	if (data + FM1_HEADER_SIZE > dataend) {
		goto overflow;
	}

	*msize = getbe32(data);
	data += 4;
	mtime = getbefloat64(data);
	data += 8;
	tz = getbeint16(data);
	data += 2;
	flags = getbeuint16(data);
	data += 2;

	if (flags & USING_SHA_256) {
		hashwidth = 32;
	}

	nsuccs = (unsigned char)(*data++);
	nparents = (unsigned char)(*data++);
	nmetadata = (unsigned char)(*data++);

	if (databegin + *msize > dataend) {
		goto overflow;
	}
	dataend = databegin + *msize; /* narrow down to marker size */

	if (data + hashwidth > dataend) {
		goto overflow;
	}
	prec = PyBytes_FromStringAndSize(data, hashwidth);
	data += hashwidth;
	if (prec == NULL) {
		goto bail;
	}

	if (data + nsuccs * hashwidth > dataend) {
		goto overflow;
	}
	succs = readshas(data, nsuccs, hashwidth);
	if (succs == NULL) {
		goto bail;
	}
	data += nsuccs * hashwidth;

	if (nparents == 1 || nparents == 2) {
		if (data + nparents * hashwidth > dataend) {
			goto overflow;
		}
		parents = readshas(data, nparents, hashwidth);
		if (parents == NULL) {
			goto bail;
		}
		data += nparents * hashwidth;
	} else {
		parents = Py_None;
		Py_INCREF(parents);
	}

	if (data + 2 * nmetadata > dataend) {
		goto overflow;
	}
	meta = data + (2 * nmetadata);
	metadata = PyTuple_New(nmetadata);
	if (metadata == NULL) {
		goto bail;
	}
	for (i = 0; i < nmetadata; i++) {
		PyObject *tmp, *left = NULL, *right = NULL;
		Py_ssize_t leftsize = (unsigned char)(*data++);
		Py_ssize_t rightsize = (unsigned char)(*data++);
		if (meta + leftsize + rightsize > dataend) {
			goto overflow;
		}
		left = PyBytes_FromStringAndSize(meta, leftsize);
		meta += leftsize;
		right = PyBytes_FromStringAndSize(meta, rightsize);
		meta += rightsize;
		tmp = PyTuple_New(2);
		if (!left || !right || !tmp) {
			Py_XDECREF(left);
			Py_XDECREF(right);
			Py_XDECREF(tmp);
			goto bail;
		}
		PyTuple_SET_ITEM(tmp, 0, left);
		PyTuple_SET_ITEM(tmp, 1, right);
		PyTuple_SET_ITEM(metadata, i, tmp);
	}
	ret = Py_BuildValue("(OOHO(di)O)", prec, succs, flags, metadata, mtime,
	                    (int)tz * 60, parents);
	goto bail; /* return successfully */

overflow:
	PyErr_SetString(PyExc_ValueError, "overflow in obsstore");
bail:
	Py_XDECREF(prec);
	Py_XDECREF(succs);
	Py_XDECREF(metadata);
	Py_XDECREF(parents);
	return ret;
}

static PyObject *fm1readmarkers(PyObject *self, PyObject *args)
{
	const char *data, *dataend;
	Py_ssize_t datalen, offset, stop;
	PyObject *markers = NULL;

	if (!PyArg_ParseTuple(args, PY23("s#nn", "y#nn"), &data, &datalen,
	                      &offset, &stop)) {
		return NULL;
	}
	if (offset < 0) {
		PyErr_SetString(PyExc_ValueError,
		                "invalid negative offset in fm1readmarkers");
		return NULL;
	}
	if (stop > datalen) {
		PyErr_SetString(
		    PyExc_ValueError,
		    "stop longer than data length in fm1readmarkers");
		return NULL;
	}
	dataend = data + datalen;
	data += offset;
	markers = PyList_New(0);
	if (!markers) {
		return NULL;
	}
	while (offset < stop) {
		uint32_t msize;
		int error;
		PyObject *record = fm1readmarker(data, dataend, &msize);
		if (!record) {
			goto bail;
		}
		error = PyList_Append(markers, record);
		Py_DECREF(record);
		if (error) {
			goto bail;
		}
		data += msize;
		offset += msize;
	}
	return markers;
bail:
	Py_DECREF(markers);
	return NULL;
}

static char parsers_doc[] = "Efficient content parsing.";

PyObject *encodedir(PyObject *self, PyObject *args);
PyObject *pathencode(PyObject *self, PyObject *args);
PyObject *lowerencode(PyObject *self, PyObject *args);
PyObject *parse_index2(PyObject *self, PyObject *args, PyObject *kwargs);

static PyMethodDef methods[] = {
    {"pack_dirstate", pack_dirstate, METH_VARARGS, "pack a dirstate\n"},
    {"parse_dirstate", parse_dirstate, METH_VARARGS, "parse a dirstate\n"},
    {"parse_index2", (PyCFunction)parse_index2, METH_VARARGS | METH_KEYWORDS,
     "parse a revlog index\n"},
    {"isasciistr", isasciistr, METH_VARARGS, "check if an ASCII string\n"},
    {"asciilower", asciilower, METH_VARARGS, "lowercase an ASCII string\n"},
    {"asciiupper", asciiupper, METH_VARARGS, "uppercase an ASCII string\n"},
    {"dict_new_presized", dict_new_presized, METH_VARARGS,
     "construct a dict with an expected size\n"},
    {"make_file_foldmap", make_file_foldmap, METH_VARARGS,
     "make file foldmap\n"},
    {"jsonescapeu8fast", jsonescapeu8fast, METH_VARARGS,
     "escape a UTF-8 byte string to JSON (fast path)\n"},
    {"encodedir", encodedir, METH_VARARGS, "encodedir a path\n"},
    {"pathencode", pathencode, METH_VARARGS, "fncache-encode a path\n"},
    {"lowerencode", lowerencode, METH_VARARGS, "lower-encode a path\n"},
    {"fm1readmarkers", fm1readmarkers, METH_VARARGS,
     "parse v1 obsolete markers\n"},
    {NULL, NULL}};

void dirs_module_init(PyObject *mod);
void manifest_module_init(PyObject *mod);
void revlog_module_init(PyObject *mod);

static const int version = 20;

static void module_init(PyObject *mod)
{
	PyModule_AddIntConstant(mod, "version", version);

	/* This module constant has two purposes.  First, it lets us unit test
	 * the ImportError raised without hard-coding any error text.  This
	 * means we can change the text in the future without breaking tests,
	 * even across changesets without a recompile.  Second, its presence
	 * can be used to determine whether the version-checking logic is
	 * present, which also helps in testing across changesets without a
	 * recompile.  Note that this means the pure-Python version of parsers
	 * should not have this module constant. */
	PyModule_AddStringConstant(mod, "versionerrortext", versionerrortext);

	dirs_module_init(mod);
	manifest_module_init(mod);
	revlog_module_init(mod);

	if (PyType_Ready(&dirstateItemType) < 0) {
		return;
	}
	Py_INCREF(&dirstateItemType);
	PyModule_AddObject(mod, "DirstateItem", (PyObject *)&dirstateItemType);
}

static int check_python_version(void)
{
	PyObject *sys = PyImport_ImportModule("sys"), *ver;
	long hexversion;
	if (!sys) {
		return -1;
	}
	ver = PyObject_GetAttrString(sys, "hexversion");
	Py_DECREF(sys);
	if (!ver) {
		return -1;
	}
	hexversion = PyInt_AsLong(ver);
	Py_DECREF(ver);
	/* sys.hexversion is a 32-bit number by default, so the -1 case
	 * should only occur in unusual circumstances (e.g. if sys.hexversion
	 * is manually set to an invalid value). */
	if ((hexversion == -1) || (hexversion >> 16 != PY_VERSION_HEX >> 16)) {
		PyErr_Format(PyExc_ImportError,
		             "%s: The Mercurial extension "
		             "modules were compiled with Python " PY_VERSION
		             ", but "
		             "Mercurial is currently using Python with "
		             "sys.hexversion=%ld: "
		             "Python %s\n at: %s",
		             versionerrortext, hexversion, Py_GetVersion(),
		             Py_GetProgramFullPath());
		return -1;
	}
	return 0;
}

#ifdef IS_PY3K
static struct PyModuleDef parsers_module = {PyModuleDef_HEAD_INIT, "parsers",
                                            parsers_doc, -1, methods};

PyMODINIT_FUNC PyInit_parsers(void)
{
	PyObject *mod;

	if (check_python_version() == -1)
		return NULL;
	mod = PyModule_Create(&parsers_module);
	module_init(mod);
	return mod;
}
#else
PyMODINIT_FUNC initparsers(void)
{
	PyObject *mod;

	if (check_python_version() == -1) {
		return;
	}
	mod = Py_InitModule3("parsers", methods, parsers_doc);
	module_init(mod);
}
#endif
