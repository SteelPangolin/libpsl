/*
 * Copyright(c) 2014 Tim Ruehsen
 *
 * Permission is hereby granted, free of charge, to any person obtaining a
 * copy of this software and associated documentation files (the "Software"),
 * to deal in the Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute, sublicense,
 * and/or sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
 * DEALINGS IN THE SOFTWARE.
 *
 * This file is part of libpsl.
 *
 * Precompile Public Suffix List into a C source file
 *
 * Changelog
 * 22.03.2014  Tim Ruehsen  created
 *
 */

#if HAVE_CONFIG_H
# include <config.h>
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/stat.h>
#ifdef HAVE_ALLOCA_H
#	include <alloca.h>
#endif

#if defined(BUILTIN_GENERATOR_LIBICU) || defined(BUILTIN_GENERATOR_LIBIDN2) || defined(BUILTIN_GENERATOR_LIBIDN)
#	define _GENERATE_BUILTIN_DATA
#endif

#ifdef _GENERATE_BUILTIN_DATA

#include <libpsl.h>

/* here we include the library source code to have access to internal functions and data structures */
#define _LIBPSL_INCLUDED_BY_PSL2C
#	include "psl.c"
#undef _LIBPSL_INCLUDED_BY_PSL2C

static int _check_psl_entries(const _psl_vector_t *v)
{
	int it, doublet = 0, err = 0;

	for (it = 0; it < v->cur - 1; it++) {
		_psl_entry_t *cur = _vector_get(v, it);
		_psl_entry_t *next = _vector_get(v, it + 1);

		if (_suffix_compare(cur, next) == 0) {
			/* we allow '*.foo' and 'foo' */
			if (cur->wildcard == next->wildcard) {
				fprintf(stderr, "Double entry '%s' detected\n", cur->label);
				err = 1;
			}
			else if (++doublet > 1) {
				fprintf(stderr, "Double entry '%s' detected\n", cur->label);
				err = 1;
			}
		} else
			doublet = 0;
	}

	return err;
}

static int _check_psl(const psl_ctx_t *psl)
{
	int it, pos, err = 0;

	if (_check_psl_entries(psl->suffixes))
		err = 1;

	if (_check_psl_entries(psl->suffix_exceptions))
		err = 1;

	/* check if plain suffix also appears in exceptions */
	for (it = 0; it < psl->suffixes->cur; it++) {
		_psl_entry_t *e = _vector_get(psl->suffixes, it);

		if (!e->wildcard && _vector_find(psl->suffix_exceptions, e) >= 0) {
			fprintf(stderr, "Found entry '%s' also in exceptions\n", e->label);
			err = 1;
		}
	}

	/* check if exception also appears in suffix list as plain entry */
	for (it = 0; it < psl->suffix_exceptions->cur; it++) {
		_psl_entry_t *e2, *e = _vector_get(psl->suffix_exceptions, it);

		if ((e2 = _vector_get(psl->suffixes, pos = _vector_find(psl->suffixes, e)))) {
			if (!e2->wildcard) {
				fprintf(stderr, "Found exception '!%s' also as suffix\n", e->label);
				err = 1;
			}
			/* Two same domains in a row are allowed: wildcard and non-wildcard.
			 * Binary search find either of them, so also check previous and next entry. */
			else if (pos > 0 && _suffix_compare(e, e2 = _vector_get(psl->suffixes, pos - 1)) == 0 && !e2->wildcard) {
				fprintf(stderr, "Found exception '!%s' also as suffix\n", e->label);
				err = 1;
			}
			else if (pos < psl->suffixes->cur - 1 && _suffix_compare(e, e2 = _vector_get(psl->suffixes, pos + 1)) == 0 && !e2->wildcard) {
				fprintf(stderr, "Found exception '!%s' also as suffix\n", e->label);
				err = 1;
			}
		}
	}

	/* check if non-wildcard entry is already covered by wildcard entry */
	for (it = 0; it < psl->suffixes->cur; it++) {
		const char *p;
		_psl_entry_t *e = _vector_get(psl->suffixes, it);

		if (e->nlabels > 1 && !e->wildcard && (p = strchr(e->label, '.'))) {
			_psl_entry_t *e2, *e3, suffix;

			suffix.label = p + 1;
			suffix.length = strlen(p + 1);
			suffix.nlabels = e->nlabels - 1;

			e2 = _vector_get(psl->suffixes, pos = _vector_find(psl->suffixes, &suffix));

			if (e2) {
				if (e2->wildcard) {
					fprintf(stderr, "Found superfluous '%s' already covered by '*.%s'\n", e->label, e2->label);
					err = 1;
				}
				/* Two same domains in a row are allowed: wildcard and non-wildcard.
				* Binary search find either of them, so also check previous and next entry. */
				else if (pos > 0 && _suffix_compare(e2, e3 = _vector_get(psl->suffixes, pos - 1)) == 0 && e3->wildcard) {
					fprintf(stderr, "Found superfluous '%s' already covered by '*.%s'\n", e->label, e2->label);
					err = 1;
				}
				else if (pos < psl->suffixes->cur - 1 && _suffix_compare(e2, e3 = _vector_get(psl->suffixes, pos + 1)) == 0 && e3->wildcard) {
					fprintf(stderr, "Found superfluous '%s' already covered by '*.%s'\n", e->label, e2->label);
					err = 1;
				}
			}
		}
	}

	return err;
}

static void _print_psl_entries(FILE *fpout, const _psl_vector_t *v, const char *varname)
{
	int it;

#ifdef BUILTIN_GENERATOR_LIBICU
	do {
		UVersionInfo version_info;
		char version[U_MAX_VERSION_STRING_LENGTH];

		u_getVersion(version_info);
		u_versionToString(version_info, version);
		fprintf(fpout, "/* automatically generated by psl2c (punycode generated with libicu/%s) */\n", version);
	} while (0);
#elif defined(BUILTIN_GENERATOR_LIBIDN2)
		fprintf(fpout, "/* automatically generated by psl2c (punycode generated with libidn2/%s) */\n", idn2_check_version(NULL));
#elif defined(BUILTIN_GENERATOR_LIBIDN)
		fprintf(fpout, "/* automatically generated by psl2c (punycode generated with libidn/%s) */\n", stringprep_check_version(NULL));
#else
	fprintf(fpout, "/* automatically generated by psl2c (without punycode support) */\n");
#endif

	fprintf(fpout, "static _psl_entry_t %s[] = {\n", varname);

	for (it = 0; it < v->cur; it++) {
		_psl_entry_t *e = _vector_get(v, it);

		fprintf(fpout, "\t{ \"%s\", NULL, %hd, %d, %d },\n",
			e->label_buf, e->length, (int) e->nlabels, (int) e->wildcard);
	}

	fprintf(fpout, "};\n");
}

#if 0
#if !defined(WITH_LIBICU) && !defined(WITH_IDN2)
static int _str_needs_encoding(const char *s)
{
	while (*s && *((unsigned char *)s) < 128) s++;

	return !!*s;
}

static void _add_punycode_if_needed(_psl_vector_t *v)
{
	int it, n;

	/* do not use 'it < v->cur' since v->cur is changed by _vector_add() ! */
	for (it = 0, n = v->cur; it < n; it++) {
		_psl_entry_t *e = _vector_get(v, it);

		if (_str_needs_encoding(e->label_buf)) {
			_psl_entry_t suffix, *suffixp;
			char lookupname[64] = "";

			/* this is much slower than the libidn2 API but should have no license issues */
			FILE *pp;
			char cmd[16 + sizeof(e->label_buf)];
			snprintf(cmd, sizeof(cmd), "idn2 '%s'", e->label_buf);
			if ((pp = popen(cmd, "r"))) {
				if (fscanf(pp, "%63s", lookupname) >= 1 && strcmp(e->label_buf, lookupname)) {
					/* fprintf(stderr, "idn2 '%s' -> '%s'\n", e->label_buf, lookupname); */
					_suffix_init(&suffix, lookupname, strlen(lookupname));
					suffix.wildcard = e->wildcard;
					suffixp = _vector_get(v, _vector_add(v, &suffix));
					suffixp->label = suffixp->label_buf; /* set label to changed address */
				}
				pclose(pp);
			} else
				fprintf(stderr, "Failed to call popen(%s, \"r\")\n", cmd);
		}
	}

	_vector_sort(v);
}
#endif /* !defined(WITH_LIBICU) && !defined(WITH_IDN2) */
#endif

#endif /* _GENERATE_BUILTIN_DATA */

int main(int argc, const char **argv)
{
	FILE *fpout;
#ifdef _GENERATE_BUILTIN_DATA
	psl_ctx_t *psl;
#endif
	int ret = 0;

	if (argc != 3) {
		fprintf(stderr, "Usage: psl2c <infile> <outfile>\n");
		fprintf(stderr, "  <infile>  is the 'public_suffix_list.dat', lowercase UTF-8 encoded\n");
		fprintf(stderr, "  <outfile> is the the C filename to be generated from <infile>\n");
		return 1;
	}

#ifdef _GENERATE_BUILTIN_DATA
	if (!(psl = psl_load_file(argv[1])))
		return 2;

	/* look for ambigious or double entries */
	if (_check_psl(psl)) {
		psl_free(psl);
		return 5;
	}

	if ((fpout = fopen(argv[2], "w"))) {
		FILE *pp;
		struct stat st;
		size_t cmdsize = 16 + strlen(argv[1]);
		char *cmd = alloca(cmdsize), checksum[64] = "";
		const char *source_date_epoch = NULL;

#if 0
		/* include library code did not generate punycode, so let's do it for the builtin data */
		_add_punycode_if_needed(psl->suffixes);
		_add_punycode_if_needed(psl->suffix_exceptions);
#endif

		_print_psl_entries(fpout, psl->suffixes, "suffixes");
		_print_psl_entries(fpout, psl->suffix_exceptions, "suffix_exceptions");

		snprintf(cmd, cmdsize, "sha1sum %s", argv[1]);
		if ((pp = popen(cmd, "r"))) {
			if (fscanf(pp, "%63[0-9a-zA-Z]", checksum) < 1)
				*checksum = 0;
			pclose(pp);
		}

		if (stat(argv[1], &st) != 0)
			st.st_mtime = 0;
		fprintf(fpout, "static time_t _psl_file_time = %lu;\n", st.st_mtime);
		if ((source_date_epoch = getenv("SOURCE_DATE_EPOCH")))
			fprintf(fpout, "static time_t _psl_compile_time = %lu;\n", atol(source_date_epoch));
		else
			fprintf(fpout, "static time_t _psl_compile_time = %lu;\n", time(NULL));
		fprintf(fpout, "static const char _psl_sha1_checksum[] = \"%s\";\n", checksum);
		fprintf(fpout, "static const char _psl_filename[] = \"%s\";\n", argv[1]);

		if (fclose(fpout) != 0)
			ret = 4;
	} else {
		fprintf(stderr, "Failed to write open '%s'\n", argv[2]);
		ret = 3;
	}

	psl_free(psl);
#else
	if ((fpout = fopen(argv[2], "w"))) {
		fprintf(fpout, "static _psl_entry_t suffixes[1];\n");
		fprintf(fpout, "static _psl_entry_t suffix_exceptions[1];\n");
		fprintf(fpout, "static time_t _psl_file_time;\n");
		fprintf(fpout, "static time_t _psl_compile_time;\n");
		fprintf(fpout, "static const char _psl_sha1_checksum[] = \"\";\n");
		fprintf(fpout, "static const char _psl_filename[] = \"\";\n");

		if (fclose(fpout) != 0)
			ret = 4;
	} else {
		fprintf(stderr, "Failed to write open '%s'\n", argv[2]);
		ret = 3;
	}
#endif /* GENERATE_BUILTIN_DATA */

	return ret;
}
