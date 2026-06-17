# Basin Infiltration Modeling Software (BaSIM)

A Python-based tool for modeling stormwater infiltration basins using MODFLOW 6 and the LAK (Lake) package. This software allows engineers to quickly size and analyze infiltration basins by importing TS1 hydrograph files and running transient groundwater models.

## 🎯 Features

- **Import DRAINS TS1 files**: Automatically parse hydrograph data from DRAINS software
- **Basin parameter input**: Enter key design parameters (dimensions, hydraulic properties)
- **Automated MODFLOW 6 modeling**: Complete model setup with LAK package for basin-aquifer interaction
- **Transient simulation**: Model basin filling and emptying over time
- **Professional visualization**: Groundwater contour plots and basin stage time series
- **Adaptive grid sizing**: Automatically adjusts model grid based on basin dimensions
- **Input validation**: Parameter range checking with user-friendly warnings

## 🛠️ Installation

### Prerequisites
- Python 3.8 or higher
- MODFLOW 6.6.2 executable at: `C:\Users\patri\OneDrive\Documents\mf6.6.2_win64\bin\mf6.exe`
- DRAINS TS1 files in: `C:\Users\patri\OneDrive\BaSIM\DRAINS\OUTPUT\`

### Setup Instructions

1. **Navigate to project directory:**
   ```bash
   cd C:\Users\patri\OneDrive\BaSIM
   ```

2. **Create and activate virtual environment:**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Verify installation:**
   ```bash
   python src\test_functions.py
   ```

## 🚀 Usage

### Running the Application
```bash
# Ensure virtual environment is activated
.venv\Scripts\activate

# Run the main application
python src\main.py
```

### Licensing (required for running simulations)
- Open the app and go to Help → License…
- Click “Save Request File…” to generate `license_request.json` with your machine ID.
- Send this file to your license issuer (BaSIM admin). You’ll receive a `license.lic`.
- Back in the License dialog, click “Import License…” and select your `license.lic`.
- The status bar will show your edition and days remaining. The Run button is enabled when licensed.

License storage: `%ProgramData%\BaSIM\license\license.lic`

Public key: Clients must know the issuer public key for offline verification. Either:
- Set environment variable `BASIM_PUBKEY` to the Ed25519 public key hex, or
- Embed it in `src/licensing/verifier.py` (PUBLIC_KEY_HEX).

### Input Parameters
The software will prompt for the following basin design parameters:

| Parameter | Description | Typical Range | Units |
|-----------|-------------|---------------|-------|
| Basin Length | Length of infiltration basin | 5-100 | m |
| Basin Width | Width of infiltration basin | 5-100 | m |
| Basin Depth | Maximum depth of basin | 0.5-5 | m |
| GW Clearance | Distance from basin bottom to water table | 1-10 | m |
| Hydraulic Conductivity | Soil permeability | 0.01-10 | m/day |
| Specific Yield | Drainable porosity | 0.01-0.3 | - |

### TS1 File Selection
- Select a TS1 hydrograph file using the file dialog
- Files should be in DRAINS format with time in minutes and flow in m³/s
- Sample files are available in `DRAINS\OUTPUT\` directory

## 📊 Output

The software generates:

1. **Groundwater Contour Plot**: Shows head distribution at final time step
2. **Basin Stage Hydrograph**: Time series of water level in the basin
3. **Model Files**: Complete MODFLOW 6 input and output files in `model_output\` directory
4. **Summary Statistics**: Peak flows, duration, and model performance metrics

### Output Files Location
```
model_output/
├── basin_model.hds          # Head file (groundwater levels)
├── basin_model.bud          # Budget file (water balance)
├── basin_model.lak.stage    # Lake stage file (basin water levels)
├── basin_model.lst          # MODFLOW listing file
├── model_results.png        # Combined visualization plots
└── inflow.ts               # Time series input file
```

## 🏗️ Technical Details

### Model Configuration
- **Grid System**: Adaptive cell size (1-10m) based on basin dimensions
- **Domain Size**: Minimum 5x basin size to minimize boundary effects
- **Vertical Discretization**: 10 layers with 5m thickness below basin
- **Boundary Conditions**: Constant head on domain perimeter
- **Time Stepping**: Variable time steps matching TS1 file duration

### LAK Package Implementation
- Horizontal connections between lake and aquifer at basin bottom
- Time series inflow from TS1 data with linear interpolation
- Stage-dependent infiltration rates based on hydraulic conductivity

## 🔧 Troubleshooting

### Common Issues

1. **"Module not found" errors**
   - Ensure virtual environment is activated: `.venv\Scripts\activate`
   - Reinstall packages: `pip install -r requirements.txt`

2. **MODFLOW executable not found**
   - Verify path in main.py (line ~100): Update `exe_name` parameter
   - Test executable: `C:\Users\patri\OneDrive\Documents\mf6.6.2_win64\bin\mf6.exe -v`

3. **TS1 parsing errors**
   - Check file format: Should be comma-separated with time in minutes
   - Verify file contains numeric data after header lines

4. **Model convergence issues**
   - Try smaller basin dimensions or adjust hydraulic parameters
   - Check model output files in `model_output\` for detailed error messages

### Getting Help
- Run test script: `python src\test_functions.py`
- Check console output for detailed error information
- Review MODFLOW listing file: `model_output\basin_model.lst`

## 📁 Project Structure
```
BaSIM/
├── .venv/                     # Python virtual environment
├── src/
│   ├── main.py               # Main application (334 lines)
│   └── test_functions.py     # System verification tests
├── model_output/             # MODFLOW model files and results
├── DRAINS/
│   └── OUTPUT/              # Sample TS1 hydrograph files
├── requirements.txt          # Python package dependencies
└── README.md                # This documentation
```

## 🔬 Testing and Validation

The software includes comprehensive testing:
- Package import verification
- TS1 file parsing validation
- MODFLOW executable accessibility
- Directory structure verification

Run all tests: `python src\test_functions.py`

## 📐 Technical Justification: Infiltration Sizing Approach

The public MODFLOW-USG engine utilizes an upstream weighting formulation that treats dry cell boundaries as gravity-driven seepage faces, omitting the capillary suction gradient ($\psi$). To preserve the computational speed and efficiency of unstructured quadtree grids without numerical instability, BaSIM upscales the user's clogged layer hydraulic conductivity to an Effective Conductivity ($K_{effective}$).

This is achieved by setting the steady-state MODFLOW Darcy flux equal to the transient physical Green-Ampt infiltration flux at a user-selected design head threshold:

$$K_{effective} = 0.5 \times K_{clog} \left( 1 + \frac{L_{clog} + \psi}{H_{threshold}} \right)$$

*(Note: the $0.5$ scalar is a structural mapping factor required to equate physical Darcy flow with MODFLOW's unconfined half-thickness vertical conductance formulation).*

The **Infiltration Sizing Approach** UI slider adjusts $H_{threshold}$ as a percentage of the maximum basin depth, allowing the user to select a mass-conservative lower bound for volume sizing, or an empirically grounded upper bound for rapid drawdown analysis.

## 🚀 Future Enhancements

### Planned Features
1. **Graphical User Interface**: Replace CLI with user-friendly GUI
2. **Basin Optimization**: Automatic sizing based on volume requirements
3. **Scenario Comparison**: Batch processing of multiple TS1 files
4. **Export Functionality**: Save results to Excel/CSV formats
5. **Advanced Visualization**: 3D plots and animation capabilities
6. **Configuration Management**: Save/load project settings

### Development Priorities
1. Get basic model running reliably ✅
2. Add parameter validation and error handling ✅
3. Implement GUI for better usability (next)
4. Add optimization and comparison features
5. Polish with documentation and export capabilities

## 📄 License and Disclaimer

This software is developed for engineering analysis purposes. Users should:
- Validate results against other methods
- Ensure compliance with local stormwater management regulations
- Use appropriate safety factors in design
- Consider site-specific conditions not captured in the model

## 👥 Support

For technical support:
1. Check troubleshooting section above
2. Review test output: `python src\test_functions.py`
3. Examine MODFLOW output files for detailed diagnostics
4. Refer to flopy documentation: https://flopy.readthedocs.io/

---

**Version**: 1.0.0  
**Last Updated**: August 2025  
**Python Version**: 3.8+  
**MODFLOW Version**: 6.6.2

## Packaging and Binaries

- Use PowerShell script `build.ps1` to create a Windows executable via PyInstaller.
- Optional `-DownloadMf6` flag fetches MODFLOW 6 into `bin/` and the spec bundles `bin/mf6.exe` plus any `bin/*.dll`.
- At runtime, BaSIM locates MODFLOW 6 in this order:
   1. `BASINSIM_MF6` environment variable
   2. Packaged `bin/mf6.exe` (inside the app)
   3. User override in `%USERPROFILE%\.basinsim\prefs.json` under key `mf6_path`
   4. `mf6` on system PATH

### MSI Installer (Enterprise)
- The WiX MSI creates `%ProgramData%\BaSIM\license` for system-wide license storage.
- You can set the public key during install via MSI property `BASIMPUBKEY`:
   - Example (run as admin):
      ```powershell
   msiexec /i BaSIM.msi BASIMPUBKEY=0123abcd... /qn
      ```
   - This sets a system environment variable `BASIM_PUBKEY` used by the verifier.

## 🔑 Issuing Licenses (Admin)
1. Generate an Ed25519 key pair (private kept secret, public shared with clients):
    ```python
    from nacl.signing import SigningKey
    sk = SigningKey.generate()
    priv_hex = sk.encode().hex()
    pub_hex = sk.verify_key.encode().hex()
    print('PRIVATE (keep secret):', priv_hex)
    print('PUBLIC (distribute):', pub_hex)
    ```
2. Set the public key on client machines (env `BASIM_PUBKEY`) or embed in `verifier.py`.
3. Issue a node-locked license using the provided CLI:
    ```powershell
    # In repo root
    python tools\license_issuer.py path\to\license_request.json --customer "Acme" --edition Enterprise --out license.lic --private-key-hex <PRIVATE_HEX>
    ```
4. Deliver `license.lic` to the client; they import it via Help → License…
