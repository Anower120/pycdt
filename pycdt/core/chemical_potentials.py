# coding: utf-8
"""
A class for performing analysis of chemical potentials with the grand
canonical linear programming approach
"""
from __future__ import division

__author__ = "Bharat Medasani, Nils Zimmermann, Danny Broberg"
__copyright__ = "Copyright 2014, The Materials Project"
__version__ = "1.0"
__maintainer__ = "Bharat Medasani"
__email__ = 'mbkumar@gmail.com'
__date__ = "Sep 14, 2014"

import os
import logging

from pymatgen import Structure, Element
from pymatgen.entries.computed_entries import ComputedStructureEntry
from pymatgen.ext.matproj import MPRester
from pymatgen.io.vasp.outputs import Vasprun
from pymatgen.analysis.phase_diagram import PhaseDiagram


class ChemPotAnalyzer(object):
    """
    Post processing for atomic chemical potentials used in defect
    calculations.
    """
    def __init__(self, **kwargs):
        """
        Args:
            bulk_ce: Pymatgen ComputedStructureEntry object for
                bulk entry / supercell
        """
        self.bulk_ce = kwargs.get('bulk_ce', None)

    def get_chempots_from_pd(self, pd):
        logger = logging.getLogger(__name__)

        if not self.bulk_ce:
            msg = "No bulk entry supplied. " \
                  "Cannot compute atomic chempots without knowing the bulk entry of interest."
            logger.warning(msg)
            raise ValueError(msg)
        else:
            bulk_composition = self.bulk_ce.composition
            redcomp = bulk_composition.reduced_composition

            #append bulk_ce to phase diagram
            entries = pd.all_entries
            entries.append(self.bulk_ce)
            pd = PhaseDiagram( entries)

        chem_lims = pd.get_all_chempots(redcomp)

        return chem_lims

    def diff_bulk_sub_phases(self, face_list, sub_el=None):
        # method for pulling out phases within a facet of a phase diagram
        # which may include a substitutional element...
        # face_list is an array of phases in a facet
        # sub_el is the element to look out for within the face_list array
        blk = []
        sub_spcs = []
        for face in face_list:
            if sub_el:
                if sub_el in face:
                    sub_spcs.append(face)
                else:
                    blk.append(face)
            else:
                blk.append(face)
        blk.sort()
        sub_spcs.sort()
        blknom = '-'.join(blk)
        subnom = '-'.join(sub_spcs)
        return blk, blknom, subnom


class MPChemPotAnalyzer(ChemPotAnalyzer):
    """
    Post processing for atomic chemical potentials by querying MP database

    Makes use of Materials Project pre-computed data to generate
    needed information for chem pots in different growth conditions.

    WARNING: If you plan to use this method, then you better be sure you are
    using the same settings as MP (same INCAR, POTCARs etc.)
    """
    def __init__(self, **kwargs):
        """
        Args:
            bulk_ce: Pymatgen ComputedStructureEntry object for
                bulk entry / supercell
            subs_species (set): set of elemental species that are extrinsic to structure.
                Default is no subs included
            entries (dict): a dict of pymatgen ComputedEntry objects to build relevant phase diagram
                The dict contains two keys: 'bulk_derived', and 'subs_set', each contains a list of ComputedEntry objects
                'bulk_derived' list only has compositions containing elements from the bulk (un-defective) composition
                'subs_set' list has compositions which contain at least one element that is not in the bulk composition
            mpid (str): Materials Project ID of bulk structure (not required, can use bulk_ce instead);
                format "mp-X", where X is an integer;
            mapi_key (str): Materials API key to access database
                (if not in ~/.pmgrc.yaml already)
        """
        super(self.__class__, self).__init__(**kwargs)
        self.sub_species = kwargs.get('sub_species', set())
        self.entries = kwargs.get('entries', {})
        self.mpid = kwargs.get('mpid', None)
        self.mapi_key = kwargs.get('mapi_key', None)

    def analyze_GGA_chempots(self, full_sub_approach=False):
        """
        For calculating GGA-PBE atomic chemical potentials by using
            Materials Project pre-computed data

        Args:
            full_sub_approach: generate chemical potentials by looking at
                full phase diagram (setting to True is NOT recommended
                if subs_species set has more than one element in it...)

        This code retrieves atomic chempots from Materials
        Project (MP) entries by making use of the pymatgen
        phase diagram (PD) object and computed entries from the MP
        database. There are debug notes that are made based on the stability of
        the structure of interest with respect to the phase diagram generated from MP

        NOTE on 'full_sub_approach':
            The default approach for substitutional elements (full_sub_approach = False)
            is to only consider facets defined by at least N-2 phases from the BULK
            composition, and a maximum of 1 composition with extrinsic species present
            (this, along with the condition for all chemical potentials to be defined
            by the bulk entry, creates N equations to be solved for N atomic
            chemical potentials - see PyCDT paper DOI: 10.1016/j.cpc.2018.01.004).

            This default approach speeds up analysis when analyzing several substitutional
            species at the same time. It is also a justified approach, as it reflects the fact
            that substitutional elements are dilute in comparison to the composition of the
            bulk phase.

            If you prefer to consider the full phase diagram (not recommended
            unless you have less than 3 substitutional defects), then set
            full_sub_approach to True.
        """
        logger = logging.getLogger(__name__)

        #gather entries
        self.get_mp_entries(full_sub_approach=full_sub_approach)

        # figure out how system should be treated for chemical potentials
        # based on phase diagram
        entry_list = self.entries['bulk_derived']
        pd = PhaseDiagram(entry_list)

        decomp_en = round(pd.get_decomp_and_e_above_hull(
                          self.bulk_ce, allow_negative=True)[1],4)

        stable_composition_exists = False
        for i in pd.stable_entries:
            if i.composition.reduced_composition == self.redcomp:
                stable_composition_exists = True

        if (decomp_en <= 0) and stable_composition_exists:
            logger.debug(
                "Bulk Computed Entry found to be stable with respect "
                "to MP Phase Diagram (e_above_hull = {} eV/atom).".format(decomp_en))
        elif (decomp_en <= 0) and not stable_composition_exists:
            logger.info(
                "Bulk Computed Entry found to be stable with respect "
                "to MP Phase Diagram (e_above_hull = {} eV/atom).\n"
                "However, no stable entry with this composition exists "
                "in the MP database!\nPlease consider submitting the "
                "POSCAR to the MP xtaltoolkit, so future users will "
                "know about this structure:"
                " https://materialsproject.org/#apps/xtaltoolkit\n"
                "Manually inserting structure into phase diagram and "
                "proceeding as normal.".format(decomp_en))
            entry_list.append(self.bulk_ce)
        elif stable_composition_exists:
            logger.warning(
                "Bulk Computed Entry not stable with respect to MP "
                "Phase Diagram (e_above_hull = {} eV/atom), but found "
                "stable MP composition to exist.\nProducing chemical "
                "potentials with respect to stable phase.".format( decomp_en))
        else:
            logger.warning(
                "Bulk Computed Entry not stable with respect to MP "
                "Phase Diagram (e_above_hull = {} eV/atom) and no "
                "stable structure with this composition exists in the "
                "MP database.\nProceeding with atomic chemical "
                "potentials according to composition position within "
                "phase diagram.".format( decomp_en))

        pd = PhaseDiagram(entry_list)
        chem_lims = self.get_chempots_from_pd(pd)

        if not full_sub_approach:
            #NOTE if full_sub_approach was True, then all the sub_entries
            # were ported into the bulk_derived list
            finchem_lims = {}  # this will be final chem_lims dictionary
            for key in chem_lims.keys():
                face_list = key.split('-')
                blk, blknom, subnom = self.diff_bulk_sub_phases(face_list)
                finchem_lims[blknom] = {}
                finchem_lims[blknom] = chem_lims[key]

            # Now add single elements to extend the phase diagram,
            # adding new additions to chemical potentials ONLY for the cases
            # where the phases in equilibria are those from the bulk phase
            # diagram. This is essentially the assumption that the majority of
            # the elements in the total composition will be from the native
            # species present rather than the sub species (a good approximation)
            for sub_el in self.sub_species:
                sub_specie_entries = entry_list[:]
                for entry in self.entries['subs_set'][sub_el]:
                    sub_specie_entries.append(entry)

                pd = PhaseDiagram(sub_specie_entries)
                chem_lims = self.get_chempots_from_pd(pd)

                for key in chem_lims.keys():
                    face_list = key.split('-')
                    blk, blknom, subnom = self.diff_bulk_sub_phases(
                        face_list, sub_el=sub_el)
                    # if one less than number of bulk species then can be
                    # grouped with rest of structures
                    if len(blk)+1 == len(self.bulk_species_symbol):
                        if blknom not in finchem_lims.keys():
                            finchem_lims[blknom] = chem_lims[key]
                        else:
                            finchem_lims[blknom][sub_el] = \
                                chem_lims[key][Element(sub_el)]
                        if 'name-append' not in finchem_lims[blknom].keys():
                            finchem_lims[blknom]['name-append'] = subnom
                        else:
                            finchem_lims[blknom]['name-append'] += '-' + subnom
                    else:
                        # if chem pots determined by two (or more) sub-specie
                        # containing phases, skip this facet!
                        continue

            #run a check to make sure all facets dominantly defined by bulk species
            overdependent_chempot = False
            if len(finchem_lims.keys()) != len(self.bulk_species_symbol):
                overdependent_chempot = True
                logger.warning(
                "Determined chemical potentials to be over dependent"
                " on a substitutional specie. Needing to revert to full_sub_approach. If "
                "multiple sub species exist this could take a while/break the code...")

            if not overdependent_chempot:
                chem_lims = finchem_lims.copy()
            else:
                #This is for when overdetermined chempots occur, forcing the full_sub_approach to happen
                for sub, subentries in self.entries['subs_set'].items():
                    for subentry in subentries:
                        entry_list.append(subentry)
                pd = PhaseDiagram(entry_list)
                chem_lims = self.get_chempots_from_pd( pd)


        return chem_lims

    def get_chempots_from_composition(self, bulk_composition):
        """
        A simple method for getting GGA-PBE chemical potentials JUST
        from the composition information (Note: this only works if the
        composition already exists in the MP database)

        Args:
            bulk_composition : Composition of bulk as a pymatgen Composition
                object. This and mapi_key are only actual required input for
                generating set of chemical potentials from Materials Project
                database
        """
        logger = logging.getLogger(__name__)

        redcomp = bulk_composition.reduced_composition
        if not self.entries:
            self.bulk_species_symbol = [s.symbol for s in redcomp.elements]
            with MPRester(api_key=self.mapi_key) as mp:
                self.entries['bulk_derived'] = mp.get_entries_in_chemsys(self.bulk_species_symbol)

        pd = PhaseDiagram(self.entries['bulk_derived'])
        chem_lims = pd.get_all_chempots(redcomp)

        return chem_lims

    def get_mp_entries(self, full_sub_approach=False):
        """
        This queries MP database for computed entries according to
        input bulk and sub elements of interest

        Args:
            mpid (str): Structure id of the system in the MP databse.
            mapi_key (str): Materials API key to access database
                (if not in ~/.pmgrc.yaml already)
        """
        logger = logging.getLogger(__name__)

        if self.bulk_ce:
            self.bulk_species_symbol = [s.symbol for s in self.bulk_ce.composition.elements]
            self.redcomp = self.bulk_ce.composition.reduced_composition
            bce_override = True
        elif self.mpid:
            with MPRester(api_key=self.mapi_key) as mp:
                self.bulk_ce = mp.get_entry_by_material_id(self.mpid)
            self.bulk_species_symbol = [s.symbol for s in self.bulk_ce.composition.elements]
            self.redcomp = self.bulk_ce.composition.reduced_composition
            bce_override = False
        else:
            msg = "No bulk entry OR mpid supplied. " \
                  "Cannot compute atomic chempots without know the bulk entry of interest."
            logger.warning(msg)
            raise ValueError(msg)

        if full_sub_approach: #this can be time consuming if several sub species exist
            species_symbols = self.bulk_species_symbol[:]
            for sub_el in self.sub_species:
                species_symbols.append(sub_el)

            with MPRester(api_key=self.mapi_key) as mp:
                self.entries['bulk_derived'] = mp.get_entries_in_chemsys(species_symbols)

            self.entries['subs_set'] = {sub_el:[] for sub_el in self.sub_species}
            for entry in self.entries['bulk_derived']:
                for sub_el in self.sub_species:
                    if sub_el in entry.composition:
                        self.entries['subs_set'][sub_el].append(entry)

        else: #this is recommended approach for running sub species seperately (assumes subs are in dilute concentrations)
            with MPRester(api_key=self.mapi_key) as mp:
                self.entries['bulk_derived'] = mp.get_entries_in_chemsys(self.bulk_species_symbol)
                if self.mpid and bce_override: #overriding bulk_ce if mp-id is given.
                    self.bulk_ce = mp.get_entry_by_material_id(self.mpid)
            if not self.entries:
                msg = "Could not fetch bulk entries for atomic chempots!" \
                      "MPRester query error."
                logger.warning(msg)
                raise ValueError(msg)

            # now compile substitution entries
            self.entries['subs_set'] = dict()
            bulk_entry_set = [entry.entry_id for entry in self.entries['bulk_derived']]
            for sub_el in self.sub_species:
                els = self.bulk_species_symbol + [sub_el]
                with MPRester(api_key=self.mapi_key) as mp:
                    sub_entry_set = mp.get_entries_in_chemsys(els)
                if not sub_entry_set:
                    msg = "Could not fetch sub entries for {} atomic chempots! " \
                          "Encountered MPRester query error".format(sub_el)
                    logger.warning(msg)
                    raise ValueError(msg)

                fin_sub_entry_set = []
                for entry in sub_entry_set:
                    if entry.entry_id not in bulk_entry_set:
                        fin_sub_entry_set.append(entry)
                # All entries apart from the bulk entry set
                self.entries['subs_set'][sub_el] = fin_sub_entry_set

        return


class UserChemPotAnalyzer(ChemPotAnalyzer):
    """
    Post processing for atomic chemical potentials based on user computed
    phase diagram entries (possibly supplemented with MP database entries)
    """
    def __init__(self, **kwargs):
        """
        Args:
            bulk_ce: Pymatgen ComputedStructureEntry object for bulk entry 
                or supercell
            path_base (str): the base path where the 'PhaseDiagram' folder 
                exists defaults to the local folder
            subs_species (set): set of elemental species that are extrinsic 
                to structure. Default is no subs included
            entries (dict): pymatgen ComputedEntry objects to build phase 
                diagram The dict contains two keys: 'bulk_derived', and 
                'subs_set', each contains a list of computed entries
                bulk_derived entries only have a composition containing 
                elements from the set of elements in the bulk phase 
                subs_set contains elements that are extrinsic to the 
                structure of interest
            mapi_key (str): Materials API key to access database
                (if not in ~/.pmgrc.yaml already)
        """
        super(self.__class__, self).__init__(**kwargs)
        self.path_base = kwargs.get('path_base', '.')
        self.sub_species = kwargs.get('sub_species', set())
        self.entries = kwargs.get('entries', {})
        self.mapi_key = kwargs.get('mapi_key', None)

    def read_phase_diagram_and_chempots(self, full_sub_approach=False, 
                                        include_mp_entries=True):
        """
        Once phase diagram has been set up and run by user (in a folder 
        called "PhaseDiagram"), this method parses and prints the chemical 
        potentials based on the computed entries. The methodology is 
        basically identical to that in the analyze_GGA_chempots method.

        Will supplement unfinished entries with MP database entries 
        unless no_mp_entries is set to False

        Args:
            full_sub_approach: same attribute as described at length in 
                the analyze_GGA_chempots method. Basically, the user can 
                set this to True if they want to mix extrinsic species 
                in the phase diagram

            include_mp_entries: if set to True, extra entries from 
                Materials Project will be added to phase diagram
                according to phases that are stable in the Materials 
                Project database

        """
        pdfile = os.path.join(self.path_base, 'PhaseDiagram')
        if not os.path.exists(pdfile):
            print ('Phase diagram file does not exist at ', pdfile)
            return

        # this is where we read computed entries into a list for parsing...
        # NOTE TO USER: If not running with VASP need to use another
        # pymatgen functionality for importing computed entries below...
        personal_entry_list = []
        for structfile in os.listdir(pdfile):
            if os.path.exists(os.path.join(pdfile, structfile, 'vasprun.xml')):
                try:
                    print('loading ',structfile)
                    vr = Vasprun(
                            os.path.join(pdfile, structfile, 'vasprun.xml'), 
                            parse_potcar_file=False)
                    personal_entry_list.append(vr.get_computed_entry())
                except:
                    print('Could not load ',structfile)

        #add bulk computed entry to phase diagram, and see if it is stable
        if not self.bulk_ce:
            vr_path = os.path.join(self.path_base, 'bulk', 'vasprun.xml')
            if os.path.exists(vr_path):
                print('loading bulk computed entry')
                bulkvr = Vasprun(vr_path)
                self.bulk_ce = bulkvr.get_computed_entry()
            else:
                print ('No bulk entry given locally. Phase diagram ' + \
                       'calculations cannot be set up without this')
                return

        self.bulk_composition = self.bulk_ce.composition
        self.redcomp = self.bulk_composition.reduced_composition

        # Supplement entries to phase diagram with those from MP database 
        if include_mp_entries:
            mpcpa = MPChemPotAnalyzer(
                    bulk_ce=self.bulk_ce, sub_species=self.sub_species, 
                    mapi_key=self.mapi_key)
            tempcl = mpcpa.analyze_GGA_chempots(
                    full_sub_approach=full_sub_approach) # Use MPentries 

            curr_pd = PhaseDiagram(list(set().union(mpcpa.entries['bulk_derived'], mpcpa.entries['subs_set'])))
            stable_idlist = {i.composition.reduced_composition: [i.energy_per_atom, i.entry_id, i] for i in curr_pd.stable_entries}
            for mpcomp, mplist in stable_idlist.items():
                matched = False
                for pe in personal_entry_list:
                    if (pe.composition.reduced_composition == mpcomp):
                        # #USER: uncomment this if you want additional stable phases of identical composition included in your phase diagram
                        # if personalentry.energy_per_atom > mplist[0]:
                        #     print('Adding entry from MP-database:',mpcomp,'(entry-id:',mplist[1])
                        #     personal_entry_list.append(mplist[2])
                        matched = True
                if not matched:
                    print('Adding entry from MP-database:', mpcomp, 
                          '(entry-id:', mplist[1])
                    personal_entry_list.append(mplist[2])
        else:
            personal_entry_list.append(self.bulk_ce)
            #if you dont have entries for elemental corners of phase diagram then code breaks
            #manually inserting entries with energies of zero for competeness...USER DO NOT USE THIS
            eltcount = {elt:0 for elt in set(self.bulk_ce.composition.elements)}
            for pentry in personal_entry_list:
                if pentry.is_element:
                    eltcount[pentry.composition.elements[0]] += 1
            for elt, eltnum in eltcount.items():
                if not eltnum:
                    s = Structure([[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]], [elt],[[0,0,0]])
                    eltentry = ComputedStructureEntry(s, 0.)
                    print('USER! Note that you have added a fake '+str(elt)+' structure to prevent from breaking the '
                          'Phase Diagram Analyzer.\n As a result DO NOT trust the chemical potential results for regions '
                          'of phase diagram that involve the element '+str(elt))
                    personal_entry_list.append(eltentry)


        personal_entry_list.append(self.bulk_ce)

        #compute chemical potentials
        if full_sub_approach:
            pd = PhaseDiagram(personal_entry_list)
            chem_lims = self.get_chempots_from_pd( pd)
        else:
            #first seperate out the bulk associated elements from those of substitutional elements
            entry_list = []
            sub_associated_entry_list = []
            for localentry in personal_entry_list:
                bulk_associated = True
                for elt in localentry.composition.elements:
                    if elt not in self.bulk_composition.elements:
                        bulk_associated = False

                if bulk_associated:
                    entry_list.append(localentry)
                else:
                    sub_associated_entry_list(localentry)

            #now iterate through and collect chemical potentials
            pd = PhaseDiagram(entry_list)
            chem_lims = self.get_chempots_from_pd( pd)

            finchem_lims = {}  # this will be final chem_lims dictionary
            for key in chem_lims.keys():
                face_list = key.split('-')
                blk, blknom, subnom = self.diff_bulk_sub_phases(face_list)
                finchem_lims[blknom] = {}
                finchem_lims[blknom] = chem_lims[key]

            # Now consider adding single elements to extend the phase diagram,
            # adding new additions to chemical potentials ONLY for the cases
            # where the phases in equilibria are those from the bulk phase
            # diagram. This is essentially the assumption that the majority of
            # the elements in the total composition will be from the native
            # species present rather than the sub species (a good approximation)
            for sub_el in self.sub_species:
                sub_specie_entries = entry_list[:]
                for entry in sub_associated_entry_list:
                    if sub_el in entry.composition.elements:
                        sub_specie_entries.append(entry)

                pd = PhaseDiagram(sub_specie_entries)
                chem_lims = self.get_chempots_from_pd(pd)

                for key in chem_lims.keys():
                    face_list = key.split('-')
                    blk, blknom, subnom = self.diff_bulk_sub_phases(
                        face_list, sub_el=sub_el)
                    # if one less than number of bulk species then can be
                    # grouped with rest of structures
                    if len(blk)+1 == len(self.bulk_species_symbol):
                        if blknom not in finchem_lims.keys():
                            finchem_lims[blknom] = chem_lims[key]
                        else:
                            finchem_lims[blknom][sub_el] = \
                                chem_lims[key][sub_el]
                        if 'name-append' not in finchem_lims[blknom].keys():
                            finchem_lims[blknom]['name-append'] = subnom
                        else:
                            finchem_lims[blknom]['name-append'] += '-' + subnom
                    else:
                        # if chem pots determined by two (or more) sub-specie
                        # containing phases, skip this facet!
                        continue
            chem_lims = finchem_lims.copy()

        return chem_lims


class UserChemPotInputGenerator(object):
    """
    For setting up phase diagram for user, based on structures that exist in the MP database
    """

    def __init__(self, bulk_composition, sub_species=set(), path_base='.', mapi_key=None):
        """
        Args:
            bulk_composition : Composition of bulk as a pymatgen Composition
                object. This and mapi_key are only actual required input for
                generating set of chemical potentials from Materials Project
                database
            subs_species : set of elemental species that are extrinsic to
                structure defaults to No substitutions needed.
            path_base (str): the base path where the 'PhaseDiagram' folder should be created
                defaults to the local folder
            mapi_key (str): Materials API key to access database
                (if not in ~/.pmgrc.yaml already)
        """
        self.bulk_composition = bulk_composition
        self.bulk_species_symbol = [s.symbol for s in bulk_composition.elements]
        self.redcomp = bulk_composition.reduced_composition
        self.sub_species = sub_species
        self.path_base = path_base
        self.mapi_key = mapi_key
        self.MPC = MPChemPotAnalyzer()

    def setup_phase_diagram_calculations(self, full_phase_diagram = False, energy_above_hull = 0, struct_fmt = 'poscar'):
        """
        This method allows for setting up local phase diagram calculations so a user can calculate
        chemical potentials on a level of interest beyond PBE-GGA/GGA+U
        Method is to pull the MP phase diagram and use PBE-GGA level data to decide which phases need to be computed

        full_phase_diagram flag has two options:
            False: set up the structures/phases which are stable in GGA phase diagram and are relevant for defining
                    the chemical potentials (exist to define the facets adjacent to composition of interest)
            True:  set up the full phase diagram according to all the entries in the MP database with elements of interest

        entry_above_hull: allows for a range of energies above hull for each composition being set up
                default is 0, meaning just the PBE-GGA ground state phases are set up. If you set value to 0.5 then all
                phases within 0.5 eV/atom of PBE-GGA ground state hull will be set up etc.

        struct_fmt: is file format you want structure to be written as. Options are “cif”, “poscar”, “cssr”, and “json”

        """

        #while GGA chem pots won't be used here; use this method for quickly gathering phase diagram object entries
        #   AND to find phases of interest if you just want to re-calculate local facets
        MPgga_muvals = self.MPC.get_chempots_from_composition(self.bulk_composition)

        if full_phase_diagram:
            setupphases = set([localentry.name for entrykey in self.MPC.entries.keys()
                               for localentry in self.MPC.entries[entrykey]]) #all elements in phase diagram
        else:
            if len(self.bulk_composition)==2: #neccessary because binary species have chempots written as "A-rich, B-rich"
                setupphases = set([phase.split('_')[0] for facet in MPgga_muvals.keys() for phase in facet.split('-')])
            else:
                setupphases = set([phase for facet in MPgga_muvals.keys() for phase in facet.split('-')]) #just local facets

        structures_to_setup = {}   #this will be a list of structure objects which need to be setup locally

        #create phase diagram object for analyzing PBE-GGA energetics of structures computed in MP database
        full_structure_entries = [struct for entrykey in self.MPC.entries.keys() for struct in self.MPC.entries[entrykey]]
        pd = PhaseDiagram(full_structure_entries)

        for entry in full_structure_entries:
            if (entry.name in setupphases) and (pd.get_decomp_and_e_above_hull(entry, allow_negative=True)[1] <= energy_above_hull):
                with MPRester(api_key=self.mapi_key) as mp:
                    localstruct = mp.get_structure_by_material_id(entry.entry_id)
                structures_to_setup[str(entry.entry_id)+'_'+str(entry.name)] = localstruct

        #Set up structure files locally if desired
        if os.path.exists(os.path.join(self.path_base,'PhaseDiagram')):
            print ('phase diagram already exists! Dont overwrite...')
        else:
            os.makedirs(os.path.join(self.path_base,'PhaseDiagram'))
            for localname,localstruct in structures_to_setup.items():
                filename = os.path.join(self.path_base,'PhaseDiagram',localname)
                os.makedirs(filename)
                if struct_fmt == 'poscar':
                    outputname = 'POSCAR'
                else:
                    outputname = 'structfile'
                localstruct.to(fmt=struct_fmt,filename=os.path.join(filename, outputname))
                #NOTE TO USER. Can use pymatgen here to setup additional calculation files if interested...

        return structures_to_setup
