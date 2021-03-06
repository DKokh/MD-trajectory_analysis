#!/usr/bin/env python
# coding: utf-8

# # Script for exploring behavior of a membrane-protein system in  MD simulations:
# 
#      1.  membrane/protein/water atom density distribution along z axis (perpendicular to the membrane surface)
#      2.  area per lipid 
#      
#
# 
# 
#############################
### v 1.1
#
#    Copyright (c) 2020
#    Released under the EUPL Licence, v1.2 or any higher version
#    
### Author: Daria Kokh
#    Daria.Kokh@h-its.org
#    Heidelberg Institute of Theoretical Studies (HITS, www.h-its.org)
#    Schloss-Wolfsbrunnenweg 35
#    69118 Heidelberg, Germany
################################# 
# 
# ### Input data required:
#     trajectory file 
#     pdb file (for example, generated from the first frame)
#     
#     
# ### Packages required:
#     numpy
#     matplotlib
#     MDAnalysis
#     scipy
#     code is written on Python 3.x



#get_ipython().run_line_magic('load_ext', 'autoreload')
#get_ipython().run_line_magic('autoreload', '2')
import glob, os
import sys
import numpy as np


from matplotlib import *
from matplotlib import gridspec
import  pylab as plt


import MDAnalysis as mda
from MDAnalysis.lib.formats.libdcd import DCDFile
from MDAnalysis.analysis import contacts,align,rms
from MDAnalysis.analysis.base import AnalysisFromFunction
from MDAnalysis.coordinates.memory import MemoryReader

from scipy.ndimage.filters import gaussian_filter1d
from scipy.interpolate import make_interp_spline, BSpline


resi_name_water = "resname SOL WAT HOH TIP3"

#######################################################################
#
#     FUNCTION FOR PUTTING SYSTEM BACK INTO A Periodic Boundary BOX with a center at COM of the selected fragment
#
#######################################################################



def pbc(u,Rgr0,selection = ""):
    """
    Parameters:
    u - a frame of the trajectory object (MD universe object)
    Rgr - reference radius of gyration; 
    as a check whether the transformation is correct we compare radius of computed gyration with the reference one
    selection - group to be used to cet a center of the box
    
    Results:
    Radius of gyration of the protein 
    """
    if selection == "":
        selection = "protein "
    selection = selection + " and not name H*"

    u_CA = u.select_atoms(selection)
    sel_p = "protein and not name H*"
    
    # getting all system elements back to the box; it is important to repeat this twice in the case when protein is splitted into two parts
    u.atoms.translate(-u_CA.center_of_mass()+0.5*u.dimensions[0:3])
    u.atoms.pack_into_box(box=u.dimensions) 
    u.atoms.translate(-u_CA.center_of_mass()+0.5*u.dimensions[0:3])
    u.atoms.pack_into_box(box=u.dimensions) 
    Rgr = u.select_atoms(sel_p).radius_of_gyration()      
    if Rgr > Rgr0*1.2:
#        print("Radius of gyration is too large: %s  of that in the first frame; Try to pack system back into a box once more " %(Rgr/Rgr0)) 
        u.atoms.translate(-u_CA.center_of_mass()+0.5*u.dimensions[0:3])
        u.atoms.pack_into_box(box=u.dimensions) 
        Rgr = u.select_atoms(sel_p).radius_of_gyration()  
#        print("Radius of gyration is now: %s  of the first frame" %(Rgr/Rgr0)) 
    if Rgr > Rgr0*1.1:
        print("failed to pack the system back into a box radius of gyration is too large: %s of that in the first frame" %(Rgr/Rgr0))
    return (Rgr)


#######################################################################
#
#     FUNCTION FOR PUTTING SYSTEM BACK INTO A Periodic Boundary BOX 
#    and keep a selected fragment COM in the same place as in the reference structure
#
#######################################################################

def pbc_plane(ref,u,Rgr0,selection,shift=0):
    """
    Parameters:
    u - a frame of the trajectory object (MD universe object)
    ref - a reference frame or structure
    Rgr - reference radius of gyration; 
    as a check whether the transformation is correct we compare radius of computed gyration with the reference one
    
    Results:
    Radius of gyration of the protein 
    """ 
    """
    for i,s in enumerate(selection_list):
        if i == 0: selection =  ""
        else: selection = selection + " or "
        selection = selection +" (resname " + s[0]+ " and name " + s[1]+ " )"
    """

    u_mem = u.select_atoms(selection)    
    ref_mem = ref.select_atoms(selection)        
    u_CA = u.select_atoms("protein and not name H*")
    sel_p = "protein and not name H*"   
    u.atoms.translate(np.multiply(-u_CA.center_of_mass()+0.5*u.dimensions[0:3],[1,1,0]))
    u.atoms.pack_into_box(box=u.dimensions) 
                                                    
    u.atoms.translate(np.multiply(-u_mem.center_of_mass()+ref_mem.center_of_mass(),[0,0,1])+[0,0,shift]) # place membrane back in z
    u.atoms.pack_into_box(box=u.dimensions) 
    Rgr = u.select_atoms(sel_p).radius_of_gyration()      
    return (Rgr)




class Membrane_properties:
    
    def __init__(self,ref_pdb,sel_ligands = "",interval=(0,-1,1),d=3,dh = 3,sel_m = "resname CHL PC PA PE", sel_m_a = "resname CHL PC PA PE OL", align_mem = False, sel_align="",shift_z=0):     
        """
        PARAMETERS:
        ref - file with a reference pdb structure
        sel_ligands - ligand residue name (or several names space-separated) to be treated together with proteion residues
        interval - array containing the first and the last frame, and a stride to be used for analysis
        sel_m - a string defining selection of the residues for membrane analysis. 
            Note, that in AMBER ff PC/PE + PA + OL - are different residues representing one lipid molecules
            particularly, OL and PA are two chains of POPC or POPE lipid that are placed in the same z - interval
            PC or PE are on the top of the lipid and practically do not overlap with PA/OL
            Thus, OL should be omitted to avouid double counting of lipid residues
            if sel_m = [], then membrane will de defined as all residues except for the protein and ligand (residue name sel_ligands)
        d= interval for splitting simulation box (the same in x/y directions, in Angstrom);  3 Angstrom default
        dh = 3 Angstrom over z
        
        align_mem - if True align membrane plane, use sel_align selection to define  membrane surface atoms
            otherwise protein (or stoms from align_list ) will be used to center the box
        
        Important: 
            - there is no averaging over z, so the best selection for dh is a vdW distance
            - for large x/y steps (d > 3 A)  the area in x/y plane occupied by ligand/protein will be overestimated
                and the atom density will be underestimated because the unit cell is assuming to be completely ocupied by a single atom 
       """
        # input parameters
        self.ref_pdb = ref_pdb
        self.sel_ligands = sel_ligands
        self.align_mem = align_mem  #how protein will be aligned- True  use align_list variable to put the membrane in the x/y plane
        self.sel_align =  sel_align
        if  self.align_mem:
            if self.sel_align == "":
                self.align_mem = False
                print("Please provide a selection to be used to orient membrane in the x/y plane: for example, sel_align = \" resname PC and name P31\"")
        self.interval = interval # defines frames of the trajectory to be processed ( first, last, stirde)
        self.dz = d
        self.dh = dh # approximate vdW distance that defines a unit slab 
        self.shift_z = shift_z # shift system position over z
        
        if sel_m_a == "": # for computing all atom number
            self.sel_m_a  = "(not type H ) and (not protein) "
            if sel_ligands != "":
                self.sel_m_a  = self.sel_m_a  +" and (resname "+ sel_ligands+" )"
        else:
            self.sel_m_a = sel_m_a +" and (not name H* )"   
            
        if sel_m == "":# for computing lipid number
            self.sel_m = self.sel 
        else: 
            self.sel_m = sel_m
            
        self.margin = max(2,int(4.0/d)+1)  # additional margin used, it is added to each side of the box in the case if box size increases along the trajectory
        
        # per-frame data:
            # arrays of numpy 3D matrices: [frame][z, x, y] 
        self.mem_slab = []
        self.mem_resid_slab = []
        self.prot_slab = []
        self.wat_slab = []
        mem_resid_slab  = []
            # arrays of vectors: [frame][z] 
        self.prot_area = []
        self.mem_area = []
        self.wat_area = []
        self.tot_area = []
        self.resid_array = []
        self.dens_p = []
        self.dens_w = []
        self.dens_m = []    
        self.m_r_per_area = []
            # arrays of arrays: [frame][z][x]  
        self.resid_array_zx = []
            # vector [frame]
        self.Rgr = []
        
        # data averaged over frames
        # array of numpy matrices [zi][x,y], where zi - includes only z value withing a membrane region (see parameters start_mem,stop.mem, and step.mem)
        self.mem_slab_frame = []
        self.mem_resid_slab_frame = [] 
        self.prot_slab_frame = []
            # array of numpy matrices [zi][x], where zi - includes only  membrane region
        self.mem_slab_frame_zx = []
        self.area_x = []
        
        # position of the membrane in the box;  used for plotting
        self.start_mem = None
        self.stop_mem = None
        self.step_mem = None
        return

###########################################
#
#  Function for computing properties of a
#  membrane-containing system for a trajectory
# 
#############################################

    def Get_info(self,traj):
        """
        PARAMETERS:
        
        traj - trajectory file
        
        Returns:
        
        arrays containing per-frame system analysis:
        1.  arrays of the shape [frame][z, x, y] containing
            mem_slab -  the number of membrane atom (as defined by the parameter sel_m_a)
            mem_resid_slab -  the number of membrane atom (as defined by the parameter sel_m)
            prot_slab - the number of protein atom 
            wat_slab - the number of water atom 
        2.  arrays of the shape [frame][z] containing
            prot_area  -area occupied by protein atoms - [frames][nz] 
            mem_area   -area occupied by membrane atoms - [frames][nz] (as defined by the parameter sel_m_a)
            wat_area   -area occupied by water atoms - [frames][nz]
            tot_area   -area occupied by all atoms (for checking)- [frames][nz]
        3.  array of the shape [frame][z] containing
            resid_array - number of lipid residues (as defined by the parameter sel_m)
        4.  array of the shape [frame][z][x] containing
            resid_array_zx - - number of lipid residues (as defined by the parameter sel_m)
            for each z,x slab
        Rgr - vector [frame] containing protein radius of gyration for each frame
        """    
        # load reference structure
        u = mda.Universe(self.ref_pdb,traj)  
        u_length = len(u.trajectory)
        u_size = int(os.path.getsize(traj)/(1024.*1024.))    
        try:
            ref = mda.Universe(self.ref_pdb)
        except:
            print("Warning: as the reference structure is not a PDB file, the first frame of the trajectory will be considered as a refewrence")
            ref = u[0]
        Rgr0 = ref.select_atoms("protein").radius_of_gyration() 
        all_atoms = ref.select_atoms("not type H")
               
        u_mem = u  # can be replaced by a procedure of loading trajectory in RAM
        u_mem_length = u_length
        start_analysis = self.interval[0] 
        stop_analysis = self.interval[1] 
        step_analysis = self.interval[2] 
        if(stop_analysis < 0): stop_analysis = u_mem_length
        frames = int((stop_analysis-start_analysis)/step_analysis)
        # box parameters
        u_mem.trajectory[0]
        if not self.align_mem:
            self.Rgr.append(pbc(u_mem,Rgr0))
        else:
            self.Rgr.append(pbc_plane(ref,u_mem,Rgr0, self.sel_align,self.shift_z))
        print("Reference structure")
        self.plot_3D(ref)
        print("First frame after alignment")
        self.plot_3D(u_mem)
        self.nz = int(u_mem.dimensions[2]/self.dh)+self.margin+1
        self.nx = int(u_mem.dimensions[0]/self.dz)+self.margin
        self.ny = int(u_mem.dimensions[1]/self.dz)+self.margin
        print("DIM (from traj, in Angstrom): ",u.dimensions)
        print("DIM (x/y/z, number of grid points): ",self.nx,self.ny,self.nz)
        nx = self.nx
        ny = self.ny
        nz = self.nz
        print("number of frames= %s; file size %s M" %(u_length,u_size))
        print("will be analyzed  %s frames" %(frames))

        wat_slab = []
        #sel_m = "(not type H Cl Na NA CL Cl- Na+) and (not protein) and (not resname WAT "+sel_ligands+" 2CU)  "
        #sel_m = "(not type H ) and ( resname CHL PC PA PE )  "  # PA + OL + PC makes POPC; PA and OL are two tails of POPC
        sel_m = self.sel_m
        sel_m_a = self.sel_m_a
        sel_w = "(not name H* ) and "+resi_name_water
        if len(self.sel_ligands) > 1:
            sel_p = "(not type H) and  (protein  or  (resname "+self.sel_ligands+"))"
        else:
            sel_p = "(not type H) and  protein" 
    
        self.Rgr = []
        # loop over frames

        for i0,i in enumerate(range(start_analysis,stop_analysis,step_analysis)):
            if (i0%10 == 0):
                print("frames analyzed: ",i0," current frame: ",i)
            u_mem.trajectory[i]
                  
            if not self.align_mem:
                self.Rgr.append(pbc(u_mem,Rgr0))
            else:
                self.Rgr.append(pbc_plane(ref,u_mem,Rgr0, self.sel_align,self.shift_z))
            u_mem_sel_m = u_mem.select_atoms(sel_m)
            u_mem_sel_m_a = u_mem.select_atoms(sel_m_a)
            u_mem_sel_p = u_mem.select_atoms(sel_p)            
            u_mem_sel_w = u_mem.select_atoms(sel_w)                    
            
            # count membrane atoms in each xy slab 
            mem_slab0 = np.zeros((nz,nx,ny),dtype = int)
            mem_resid_slab0 = np.zeros((nz,nx,ny),dtype = int)
            resid_list = []
            resid_list_zx = []
            for t in range(0,nz): 
                resid_list.append([])
                resid_list_zx.append([])
                for t in range(0,nx): resid_list_zx[-1].append([])
# first we will consider the case when each lipid is splitted into several different residues
# in this case sel_m_a - selection of all lipid residues, while  sel_m - selection of only lipid header (i.e. one resideu per lipid)
            if(sel_m_a != sel_m):
                for at,t in zip(u_mem_sel_m_a.positions,u_mem_sel_m_a):
                    n = t.resid
                    ix = (int)(at[0]/self.dz)
                    iy =  (int)(at[1]/self.dz)
                    iz = (int)(at[2]/self.dh)
                    try:
                        mem_slab0[iz,ix,iy] += 1
                    except:
                        print("Warning: Membrane is out of the box  residue ",t.resname,at," size:",nx,ny,nz,"index:",ix,iy,iz)
                for at,t in zip(u_mem_sel_m.positions,u_mem_sel_m):
                    n = t.resid
                    ix = (int)(at[0]/self.dz)
                    iy =  (int)(at[1]/self.dz)
                    iz = (int)(at[2]/self.dh)
                    try:
                        mem_resid_slab0[iz,ix,iy] += 1
                    except: pass
                    try:
                        if n not in resid_list[iz]: 
                            resid_list[iz].append(n)
                            resid_list_zx[iz][ix].append(n)
                    except:
                        pass
            else:
                for at,t in zip(u_mem_sel_m.positions,u_mem_sel_m):
                    n = t.resid
                    ix = (int)(at[0]/self.dz)
                    iy =  (int)(at[1]/self.dz)
                    iz = (int)(at[2]/self.dh)
                    try:
                        mem_slab0[iz,ix,iy] += 1
                        if n not in resid_list[iz]: 
                            resid_list[iz].append(n)
                            resid_list_zx[iz][ix].append(n)
                    except:
                        print("Warning: Membrane is out of the box: residue ",t.resname,at,"size:",nx,ny,nz,"index:",ix,iy,iz)
               
            prot_slab1 = np.zeros((nz,nx,ny),dtype = int)
            for at,t in zip(u_mem_sel_p.positions,u_mem_sel_p):
                    ix = (int)(at[0]/self.dz)
                    iy =  (int)(at[1]/self.dz)
                    iz = (int)(at[2]/self.dh)
                    try:
                        if mem_slab0[iz,ix,iy] == 0:
                            prot_slab1[iz,ix,iy] += 1
                    except:
                        print("Warning: Protein is out of the box - residue ",t.resname,at," size: ",nx,ny,nz,"index:",ix,iy,iz)
                        
            wat_slab2 = np.zeros((nz,nx,ny),dtype = int)
            for at,t in zip(u_mem_sel_w.positions,u_mem_sel_w):
                    ix = (int)(at[0]/self.dz)
                    iy = (int)(at[1]/self.dz)
                    iz = (int)(at[2]/self.dh)
                    try:
                        if prot_slab1[iz,ix,iy] == 0 and mem_slab0[iz,ix,iy] == 0:
                            wat_slab2[iz,ix,iy] = 1
                    except:
                        pass  # water at box boundary is not important, just skip it
                            #print("Water is out of the box ",at," size: ",nx,ny,nz," index: ",ix,iy,iz)
                        
            tot_area1 = np.zeros((nz),dtype = int)
            mem_area1 = np.zeros((nz),dtype = int)
            prot_area1 = np.zeros((nz),dtype = int)
            resid_array0 = np.zeros((nz),dtype = int)
            resid_array_zx0 = np.zeros((nz,nx),dtype = int)
            wat_area1 = np.zeros((nz),dtype = int)
            #---- ToDo - computing of the area can be done more accurately by taking into account just the area occupied by a single atom
            for iz in range(0,nz): 
                prot_area1[iz] = np.count_nonzero(prot_slab1[iz])*self.dz*self.dz
                mem_area1[iz] = np.count_nonzero(mem_slab0[iz])*self.dz*self.dz
                wat_area1[iz] = np.count_nonzero(wat_slab2[iz])*self.dz*self.dz
                tot_area1[iz] = prot_area1[iz]+mem_area1[iz]+wat_area1[iz]
                resid_array0[iz] = len(resid_list[iz])
                for ix in range(0,nx):
                    resid_array_zx0[iz][ix] = len(resid_list_zx[iz][ix])
            self.tot_area.append(tot_area1)
            self.wat_area.append(wat_area1)
            self.mem_area.append(mem_area1)
            self.prot_area.append(prot_area1)
            self.mem_slab.append(mem_slab0)
            self.mem_resid_slab.append(mem_resid_slab0)
            self.wat_slab.append(wat_slab2)
            self.prot_slab.append(prot_slab1)
            self.resid_array.append(resid_array0)
            self.resid_array_zx.append(resid_array_zx0)
        return 
    
    
   
    ##################################################
    #
    # Average membrane properties over all frames and
    # Preparation of data for plotting
    #
    ##################################################
    def Prep4plot(self):
        """
        Parameters:
        
        Results:
            dens_p - density of  protein (and ligand) atoms
            dens_m - density of  membrane atoms
            m_r_per_area - membrane residues per squared Angstrom
            
            mem_slab_frame - [z][x,y] x/y distribution of membrane atoms for a set of z slabs
            prot_slab_frame - [z][x,y] x/y distribution of protein atoms for a set of z slabs
            mem_slab_frame_zx - [z][x] number of membrane  residues for particular z and x (summed up over y)
            area_x - [z][x]  area occupied by membrane atoms for particular z and x (summed up over y)
        
        """
  
        area_xy = self.nx*self.ny*self.dz*self.dz

        # first we will estimate the position of the membrane center
        self.start_mem = np.argwhere(self.resid_array[0] > 0)[0][0]-2
        self.stop_mem = np.argwhere(self.resid_array[0] > 0)[-1][0]+2
        self.step_mem = 2

        area_p = self.prot_area
        frames = len(self.resid_array)
    
        for frame in range(0,frames):
            # ---- density of protein atoms  as function of z
            number_p = np.sum(np.sum(self.prot_slab[frame], axis=2),axis=1)
            dens_p0 = []
            for n,(a,d) in enumerate(zip(area_p[frame],number_p)):
                if(a > 0 ): dens_p0.append(d/a)
                else: dens_p0.append(0)           
            self.dens_p.append(np.asarray(dens_p0))
    
            area_m = (area_xy-self.prot_area[frame]) #-wat_area[frame])
            number_m = np.sum(np.sum(self.mem_slab[frame], axis=2),axis=1)
            dens_m0 = []
            dens_r0 = []
    
            # ---- density of membrane atoms and residues as function of z   
            for n,(a,d,r) in enumerate(zip(area_m,number_m,self.resid_array[frame])): # loop over z
                # density is non-zero only if area is non-zero, the number of lipids is more than 10 and the number of atoms is more than 75
                if(a > 0  and r > 0):  #and r > 75 d > 10
                    dens_m0.append(d/a)
                    if(d/a > 0.025):  dens_r0.append(a/r)
                    else:  dens_r0.append(0)
                else: 
                    dens_m0.append(0)
                    dens_r0.append(0)


            self.dens_m.append(np.asarray(dens_m0))
            self.m_r_per_area.append(np.asarray(dens_r0))
        
            # ---- density of membrane residues as function of z and x
            for i,z in enumerate(range(self.start_mem ,self.stop_mem,self.step_mem)): # loop over z and average over frames
                if(frame == 0): 
                    self.mem_slab_frame.append(self.mem_slab[frame][z])
                    self.mem_resid_slab_frame.append(self.mem_resid_slab[frame][z])
                    self.prot_slab_frame.append(self.prot_slab[frame][z])  
                    self.area_x.append(self.dz*self.dz*(self.nx-np.count_nonzero(self.prot_slab[frame][z],axis=1)))
#                    self.area_x.append(self.dz*self.dz*self.nx-4*np.sum(self.prot_slab[frame][z],axis=1))
                    self.mem_slab_frame_zx.append(self.resid_array_zx[frame][z])  # dencity of lipids
                else: 
                    self.mem_slab_frame[i] = np.add(self.mem_slab_frame[i],self.mem_slab[frame][z])
                    self.mem_resid_slab_frame[i] = np.add(self.mem_resid_slab_frame[i],self.mem_resid_slab[frame][z])
                    self.prot_slab_frame[i] = np.add(self.prot_slab_frame[i],self.prot_slab[frame][z])
#                    self.area_x[i]  = np.add(self.area_x[i],self.dz*self.dz*self.nx-4*np.sum(self.prot_slab[frame][z],axis=1))
                    self.area_x[i]  = np.add(self.area_x[i],self.dz*self.dz*(self.nx-np.count_nonzero(self.prot_slab[frame][z],axis=1)))
                    self.mem_slab_frame_zx[i] = np.add(self.mem_slab_frame_zx[i] ,self.resid_array_zx[frame][z])
        return

    ###########################################
    #
    # check if vectors for xz is in agreement for vectors for z;
    #
    ###########################################
    def Check(self):
        plt.plot(self.resid_array[0], label="lipids")
        plt.plot(self.prot_area[0], label="prot. area")

        plt.plot(np.sum(self.resid_array_zx[0],axis=1), alpha = 0.2,lw = 10,  label="lipids from xy")
        plt.plot(np.sum(np.count_nonzero(self.prot_slab[0],axis=1),axis=1), alpha = 0.2,lw =10, label="protein atoms")
        plt.legend(framealpha = 0.0,edgecolor ='None',loc='best')
        plt.ylabel('arb.un.', fontsize=14)
        plt.xlabel('z', fontsize=14)
        plt.show()
        return

    ###########################################
    #
    # Plot of 
    #   1. protein/membrane/water atom density as a function of z (axis perpendicular to a membrane surfce)
    #   2. area per lipid  as a function of z
    #
    ###########################################
    def Plot_mem_prot_wat_dens(self):
        """
        PARAMETERS:
        dens_p,dens_m - density of the protein and membrane atoms, respectively, as a function of z
        m_r_per_area - membrane residues per squared Angstrom  as a function of z
        prot_area, mem_area,wat_area - area occupied by atoms of protein, membrane, and water, respectively, as a function of z

        """
    
        dens_p = self.dens_p
        dens_m = self.dens_m
        m_r_per_area = self.m_r_per_area
        prot_area = self.prot_area
        mem_area = self.mem_area
        wat_area = self.wat_area
        tot_area = self.tot_area
    
        X = self.dh*np.asarray(range(0,len(dens_p[0])))            
        fig = plt.figure(figsize=(12, 6),dpi=150)
        gs = gridspec.GridSpec(2, 2,hspace=0.5) #height_ratios=[2,2,1]) #,width_ratios=[2,2,1,1])
        ax2 = plt.subplot(gs[0])
        plt.errorbar(x=X,y=np.mean(np.asarray(dens_p),axis=0),  yerr= np.std(np.asarray(dens_p),axis=0), color = "gray" , fmt='o--', markersize=1)
        plt.scatter(x=X,y=np.mean(np.asarray(dens_p),axis=0),color = 'red',alpha=0.5,s=50, label="protein")

        plt.errorbar(x=X,y=np.mean(np.asarray(dens_m),axis=0), yerr= np.std(np.asarray(dens_m),axis=0), color = "gray" , fmt='o--', markersize=1 )
        plt.scatter(x=X,y=np.mean(np.asarray(dens_m),axis=0),color = 'green',alpha=0.5,s=50, label="membr.")

        ax2.legend(framealpha = 0.0,edgecolor ='None',loc='upper top', fontsize=12)
        ax2.set_ylabel('[atoms/A^2]', fontsize=12)
        ax2.set_xlabel('z-distance [Angstrom]', fontsize=12)
        ax2.set_title('Surface density', fontsize=12)
        ax2.grid(color='gray', linestyle='-', linewidth=0.2)

        ax4 = plt.subplot(gs[1])
        m_r_per_area_onZero = np.argwhere(np.mean(np.asarray(m_r_per_area),axis=0) > 0)
        plt.errorbar(x=X[m_r_per_area_onZero],y=np.mean(np.asarray(m_r_per_area),axis=0)[m_r_per_area_onZero],\
                     yerr= np.std(np.asarray(m_r_per_area),axis=0)[m_r_per_area_onZero], color = "green" , fmt='o', markersize=1,alpha=0.5)
        plt.scatter(x=X[m_r_per_area_onZero],y=np.mean(np.asarray(m_r_per_area),axis=0)[m_r_per_area_onZero],color = 'green',alpha=0.5,s=50, label="membr.")
        ysmoothed = gaussian_filter1d(np.mean(np.asarray(m_r_per_area),axis=0)[m_r_per_area_onZero], sigma=1)
        plt.plot(X[m_r_per_area_onZero],ysmoothed,color = "green" , lw = 1)
        ax4.set_ylim(0,5+max(np.mean(np.asarray(m_r_per_area),axis=0)))
        ax4.legend(framealpha = 0.0,edgecolor ='None',loc='best', fontsize=12)
        ax4.set_ylabel('area [A^2]', fontsize=12)
        ax4.set_xlabel('z-distance [Angstrom]', fontsize=12)
        ax4.set_title('Area per lipid', fontsize=12)
        ax4.set_ylim(0, min(np.max(np.mean(np.asarray(m_r_per_area),axis=0)[m_r_per_area_onZero])+10, 200))
        ax4.grid(color='gray', linestyle='-', linewidth=0.2)
        ax4.set_xlim(np.min(X), np.max(X))
        

        ax3 = plt.subplot(gs[2])
        plt.errorbar(x=X,y=np.mean(np.asarray(prot_area),axis=0), yerr= np.std(np.asarray(prot_area),axis=0), color = "gray" , fmt='o--', markersize=1)
        plt.scatter(x=X,y=np.mean(np.asarray(prot_area),axis=0),color = 'red',alpha=0.5,s=50, label="protein")

        plt.errorbar(x=X,y=np.mean(np.asarray(mem_area),axis=0), yerr= np.std(np.asarray(mem_area),axis=0), color = 'green',alpha=0.5 , fmt='o--', markersize=1 )
        plt.scatter(x=X,y=np.mean(np.asarray(mem_area),axis=0),color = 'green',alpha=0.5,s=50, label="membr. ")

        plt.errorbar(x=X,y=np.mean(np.asarray(wat_area),axis=0), yerr= np.std(np.asarray(wat_area),axis=0), color = "gray" , fmt='o--', markersize=1 )
        plt.scatter(x=X,y=np.mean(np.asarray(wat_area),axis=0),color = 'blue',alpha=0.5,s=50, label="water ")
        
        plt.errorbar(x=X,y=np.mean(np.asarray(tot_area),axis=0),  yerr= np.std(np.asarray(tot_area),axis=0), color = "gray" , fmt='--', markersize=0.5 )
        plt.scatter(x=X,y=np.mean(np.asarray(tot_area),axis=0),color = 'k',alpha=0.5,s=20, label="total ")

        ax3.legend(framealpha = 0.0,edgecolor ='None',loc='best', fontsize=12)
        ax3.set_ylabel(r' $Angstrom^2 $ ', fontsize=12)
        ax3.set_xlabel('z-distance [Angstrom]', fontsize=12)
        ax3.set_title('Area occupied by different sub-systems', fontsize=12)
        ax3.grid(color ='gray', linestyle='-', linewidth=0.2)
        
        ax5 = plt.subplot(gs[3])
        plt.scatter(x = self.interval[2]*np.asarray(range(0,len(self.Rgr))),y=self.Rgr,color = 'blue',alpha=0.5,s=50)
        ax5.set_ylabel('Rad. of gyration [A]', fontsize=12)
        ax5.set_xlabel('frame', fontsize=12)
        ax5.set_title('Rad. of Gyration (protein) ', fontsize=12)
        ax5.grid(color='gray', linestyle='-', linewidth=0.2)
        ax5.set_ylim(0.5*max(self.Rgr),1.2*max(self.Rgr))
        plt.show()  
        return


    ###########################################
    #  
    # Plot of 
    #    1. atom distribution for a protein and a membrane at several z distances
    #    2. area per lipid at several z and x distances (averaged over y)
    #
    ###########################################

    def Plot_mem_z(self):
        """
        PARAMETERS:
        prot_slab_frame,mem_slab_frame - (z,x,y) matrix of atom densities  for protein and membrane, respectively
        mem_slab_frame_zx -(z,x) membrane residue density in the x,z slab
        area_x - (x,z) matrix of protein occupied area 
   
        """
        prot_slab_frame = self.prot_slab_frame
        mem_slab_frame = self.mem_slab_frame
        mem_resid_slab_frame = self.mem_resid_slab_frame
        mem_slab_frame_zx = self.mem_slab_frame_zx
        area_x = self.area_x

        start_mem = self.start_mem
        stop_mem = self.stop_mem
        step_mem = self.step_mem

        pl = 0
        dens_m_xy = []
        fig = plt.figure(figsize=(16, 7))
        plots = len(prot_slab_frame)
        gs = gridspec.GridSpec(4, plots,hspace=0.1,wspace = 0.5) #,height_ratios=[1,1],width_ratios=[2,2,1,1])
        middle = int(0.5*len(mem_slab_frame_zx))
        zmax = 1.5*np.max(np.divide(area_x[middle][self.margin:-self.margin],mem_slab_frame_zx[middle][self.margin:-self.margin]))
        for i,z in enumerate(range(start_mem ,stop_mem,step_mem)):
            ax1 = plt.subplot(gs[pl])    
            ax1.imshow(prot_slab_frame[i],  cmap="Reds") #interpolation='hamming'
            ax1.set_title('z='+str(self.dh*z))
            ax1.set_ylabel('protein', fontsize=10)
            plt.yticks([])
            plt.xticks([])
   
            ax3 = plt.subplot(gs[pl+plots])
            ax3.imshow(mem_slab_frame[i],  cmap="Greens") #interpolation='hamming',
            ax3.set_ylabel('membrane', fontsize=10)
            plt.yticks([])
            plt.xticks([])
            
            ax4 = plt.subplot(gs[pl+2*plots])
            ax4.imshow(mem_resid_slab_frame[i],  cmap="Greys") #interpolation='hamming',
            ax4.set_ylabel('selected lipids', fontsize=10)
            plt.yticks([])
            plt.xticks([])
            """
            ax4 = plt.subplot(gs[pl+2*plots])
            Y = np.divide(area_x[i][self.margin:-self.margin],mem_slab_frame_zx[i][self.margin:-self.margin])
            plt.scatter(x=self.dz*np.asarray(range(0,Y.shape[0])),y=Y,color = 'green',alpha=0.5,s=30)
            ysmoothed = gaussian_filter1d(Y, sigma=1)
            plt.plot(self.dz*np.asarray(range(0,Y.shape[0])),ysmoothed,color = "green" , lw = 3,alpha=0.5)
            ax4.set_ylim(0,zmax)
            ax4.grid(color='gray', linestyle='-', linewidth=0.2)
            if(i == 0): 
                ax4.set_ylabel('area/lipid [A^2]', fontsize=16)
                ax4.set_xlabel('x-distance', fontsize=16)
            """

            pl += 1
        plt.show()  
        
        return

######################### TO BE DONE
    def Plot_mem_z_frame(self,frame=0):
        """
        PARAMETERS:
        prot_slab_frame,mem_slab_frame - (z,x,y) matrix of atom densities  for protein and membrane, respectively
        mem_slab_frame_zx -(z,x) membrane residue density in the x,z slab
        area_x - (x,z) matrix of protein occupied area 
   
        """
        prot_slab_frame = self.prot_slab_frame
        mem_slab_frame = self.mem_slab_frame
        mem_slab_frame_zx = self.mem_slab_frame_zx
        prot_slab = self.prot_slab
        mem_slab = self.mem_slab  # [frame][z]
        mem_resid_slab = self.mem_resid_slab
        area_x = self.area_x

        start_mem = self.start_mem
        stop_mem = self.stop_mem
        step_mem = self.step_mem

        pl = 0
        dens_m_xy = []
        fig = plt.figure(figsize=(16, 7))
        plots = len(prot_slab_frame)
        gs = gridspec.GridSpec(4, plots,hspace=0.1,wspace = 0.5) #,height_ratios=[1,1],width_ratios=[2,2,1,1])
        middle = int(0.5*len(mem_slab_frame_zx))
        zmax = 1.5*np.max(np.divide(area_x[middle][self.margin:-self.margin],mem_slab_frame_zx[middle][self.margin:-self.margin]))
        for i,z in enumerate(range(start_mem ,stop_mem,step_mem)):
            ax1 = plt.subplot(gs[pl])    
            ax1.imshow(prot_slab[frame][i],  cmap="Reds") #interpolation='hamming'
            ax1.set_title('z='+str(self.dh*z))
            ax1.set_ylabel('protein', fontsize=10)
            plt.yticks([])
            plt.xticks([])
   
            ax3 = plt.subplot(gs[pl+plots])
            ax3.imshow(mem_slab[frame][i],  cmap="Greens") #interpolation='hamming',
            ax3.set_ylabel('membrane', fontsize=10)
            plt.yticks([])
            plt.xticks([])
            
            ax4 = plt.subplot(gs[pl+2*plots])
            ax4.imshow(mem_resid_slab[frame][i],  cmap="Oranges") #interpolation='hamming',
            ax4.set_ylabel('selected lipids', fontsize=10)
            plt.yticks([])
            plt.xticks([])
            pl += 1
        plt.show()  
        
        return
    
#########################
    def plot_3D(self,u):
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d import Axes3D# plot raw data
        from sklearn.cluster import KMeans
        """
        PARAMETERS:
  
        """
        u_at = u.select_atoms(self.sel_align)    
        u_CA = u.select_atoms("protein and name CA")    
        points = u_at.positions.T
        points_P = u_CA.positions.T
        
        km = KMeans(n_clusters=2, random_state=0).fit(points[2:].T)
        points_up = points.T[km.labels_ == 1].T
        points_down = points.T[km.labels_ == 0].T

        plt.figure()
        ax = plt.subplot(111, projection='3d')
        ax.scatter(points[0][km.labels_ == 0], points[1][km.labels_ == 0], points[2][km.labels_ == 0], color='b')
        ax.scatter(points[0][km.labels_ == 1], points[1][km.labels_ == 1], points[2][km.labels_ == 1], color='r')
        ax.scatter(points_P[0], points_P[1], points_P[2], color='k')
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        # plot plane
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        X,Y = np.meshgrid(np.arange(xlim[0], xlim[1],10),np.arange(ylim[0], ylim[1],10))
        Z = np.zeros(X.shape)
        fit = self.fit_plane(points_up)
        print("vector of the first plane:",fit.flatten())
        for r in range(X.shape[0]):
            for c in range(X.shape[1]):
                Z[r,c] = fit[0] * X[r,c] + fit[1] * Y[r,c] + fit[2]+points_up[2].mean()
        ax.plot_wireframe(X,Y,Z, color='gray', alpha=0.5) 
        
        X,Y = np.meshgrid(np.arange(xlim[0], xlim[1],10),np.arange(ylim[0], ylim[1],10))
        Z = np.zeros(X.shape)
        fit = self.fit_plane(points_down)
        print("vector of the second plane:",fit.flatten())
        for r in range(X.shape[0]):
            for c in range(X.shape[1]):
                Z[r,c] = fit[0] * X[r,c] + fit[1] * Y[r,c] + fit[2]+points_down[2].mean()
        ax.plot_wireframe(X,Y,Z, color='gray', alpha=0.5)        
        plt.show()
        return

#########################
    def fit_plane(self,points_up):
        m = points_up.shape[1]
        tmp_A = []
        tmp_b = []
        xs = points_up[0]
        ys = points_up[1]
        for i in range(m):
            tmp_A.append([xs[i], ys[i], 1])
        b = np.matrix(points_up[2]-points_up[2].mean()).T
        A = np.matrix(tmp_A)

        fit = (A.T * A).I * A.T * b
        errors = b - A * fit
        residual = np.linalg.norm(errors)
        return(fit)

#########################
    def plot_mem_surf(self):        
        """
        PARAMETERS:
  
        """
        u = mda.Universe(self.ref_pdb)  
        print("Reference structure")
        plot_3D(self,u)
        return






