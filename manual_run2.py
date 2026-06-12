import sys
import numpy as np
sys.path.append(r"c:\Users\patri\OneDrive\BaSIM v2.0\BaSIM_v1.0_source")

from flopy.utils.gridgen import Gridgen
from flopy.modflow import Modflow, ModflowDis

Lx, Ly = 200, 200
nrow, ncol = 10, 10
delr, delc = Lx / ncol, Ly / nrow
sim = Modflow()
dis = ModflowDis(sim, nrow=nrow, ncol=ncol, delr=delr, delc=delc, nlay=3)
g = Gridgen(dis, model_ws=r"C:\Users\patri\OneDrive\BaSIM v2.0\output\manual_test")
g.build()
gp = g.get_gridprops_disu5()
print(gp.keys())
print("First node center:", g.get_center(0))
