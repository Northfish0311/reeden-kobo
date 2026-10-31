#!/usr/bin/env python3
"""ARMHF architecture, dependency closure, symbol versions and strong imports."""
import collections,json,pathlib,sys
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
ROOT=pathlib.Path(__file__).resolve().parents[1];P=ROOT/'package'
dirs=[P/'runtime',P/'lib',P/'core/lib']
def parse(p):
    with p.open('rb') as f:
        e=ELFFile(f)
        assert e.elfclass==32 and e.little_endian and e.header.e_machine=='EM_ARM' and e.header.e_flags&0x400,(p,'not ARMHF')
        dyn=e.get_section_by_name('.dynamic');sym=e.get_section_by_name('.dynsym')
        copies=[]
        for section in e.iter_sections():
            if isinstance(section,RelocationSection):
                symbols=e.get_section(section['sh_link'])
                for rel in section.iter_relocations():
                    if rel['r_info_type']==20:
                        copies.append(symbols.get_symbol(rel['r_info_sym']).name)
        needed=[t.needed for t in dyn.iter_tags() if t.entry.d_tag=='DT_NEEDED'] if dyn else []
        exports={s.name for s in sym.iter_symbols() if s.entry.st_shndx!='SHN_UNDEF' and s.name} if sym else set()
        imports={s.name for s in sym.iter_symbols() if s.entry.st_shndx=='SHN_UNDEF' and s.entry.st_info.bind=='STB_GLOBAL' and s.name} if sym else set()
        vs=e.get_section_by_name('.gnu.version_d');versions={a.name for v,it in vs.iter_versions() for a in it} if vs else set()
        vs=e.get_section_by_name('.gnu.version_r');requirements={v.name:[a.name for a in it] for v,it in vs.iter_versions()} if vs else {}
        return dict(copy_relocations=copies,elf_type=e['e_type'],needed=needed,exports=exports,imports=imports,versions=versions,requirements=requirements,flags=hex(e.header.e_flags))
def resolve(n):
    for d in dirs:
        if (d/n).exists():return d/n
    raise AssertionError('Missing private dependency: '+n)
results=[]
for entry in [P/'bin/reeden-kindle',P/'lib/libreeden_kobo_compat.so',*sorted((P/'core/lib').glob('*.so*')),P/'lib/libgio-2.0.so']:
    pending=[entry];seen={};available=set()
    while pending:
        p=pending.pop()
        if p in seen:continue
        d=parse(p);assert not d['copy_relocations'],(p,'unsafe ARM COPY relocation',d['copy_relocations']);seen[p]=d;available.update(d['exports']);pending.extend(resolve(x) for x in d['needed'])
    for p,d in seen.items():
        for lib,vers in d['requirements'].items():
            target=parse(resolve(lib));assert set(vers)<=target['versions'],(p,lib,'missing versions',set(vers)-target['versions'])
        assert not d['imports']-available,(p,'unresolved strong imports',sorted(d['imports']-available))
    results.append({'entry':str(entry.relative_to(P)),'closure_libraries':len(seen),'result':'PASS'})
for p in [P/'bin/fb-guard',ROOT/'build/codec-test-armhf',ROOT/'build/input-test-armhf',ROOT/'build/compat-test-armhf',ROOT/'build/runtime-test-armhf',ROOT/'build/refresh-policy-test-armhf',ROOT/'build/power-worker-test-armhf',ROOT/'build/display-transaction-test-armhf']:
    d=parse(p);assert not d['copy_relocations'],(p,'unsafe ARM COPY relocation');results.append({'entry':str(p.relative_to(ROOT)),'flags':d['flags'],'requires':d['requirements']})
(ROOT/'build/elf-validation.json').write_text(json.dumps(results,indent=2)+'\n')
print('PASS: ARM32 hard-float, no ARM COPY relocations, private dependency closure, versioned symbols and strong imports for',len(results),'entries')
