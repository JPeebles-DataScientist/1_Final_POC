# -*- coding: utf-8 -*-
"""segmen

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/135ujV6_7rL_VXPIAKoPgXPLxbrSAYYDr
"""

import streamlit as st
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from sklearn.preprocessing import StandardScaler
import plotly.express as px
import io

# PySAL and spopt imports
import libpysal
from spopt.region import WardSpatial # Using WardSpatial

# --- Streamlit Page Configuration ---
st.set_page_config(layout="wide", page_title="HCP Geospatial Segmentation (WardSpatial)")

st.title("Interactive HCP Geospatial Segmentation Tool (with WardSpatial)")
st.markdown("""
This tool uses the **WardSpatial algorithm** for spatially constrained hierarchical clustering,
aiming to create geographically coherent territories by minimizing within-cluster variance.

**Instructions:**
1.  Upload a CSV file with columns: `hcp_id`, `trx_count`, `latitude`, `longitude`.
    *   *(Optional):* Include `state`, `city`, `zip_code` for validation.
2.  Select the desired number of territories (clusters).
3.  Adjust the Number of Neighbors for the connectivity graph.
4.  Click 'Run Segmentation'.
""")

# --- File Upload ---
uploaded_file = st.file_uploader("1. Upload your HCP Data (CSV)", type="csv")

if uploaded_file is not None:
    try:
        df = pd.read_csv(uploaded_file)
        st.success("File Uploaded Successfully!")

        # --- Data Validation ---
        required_columns = ['hcp_id', 'trx_count', 'latitude', 'longitude']
        optional_geo_columns = ['state', 'city', 'zip_code']
        present_optional_geo = [col for col in optional_geo_columns if col in df.columns]

        if not all(col in df.columns for col in required_columns):
            st.error(f"Error: CSV must contain the core columns: {', '.join(required_columns)}")
            st.stop()

        try:
            df['trx_count'] = pd.to_numeric(df['trx_count'])
            df['latitude'] = pd.to_numeric(df['latitude'])
            df['longitude'] = pd.to_numeric(df['longitude'])
        except ValueError as e:
            st.error(f"Error converting data to numeric types. Please check 'trx_count', 'latitude', 'longitude'. Details: {e}")
            st.stop()

        st.write("### Input Data Preview (First 5 Rows)")
        st.dataframe(df.head())

        initial_rows = len(df)
        df_cleaned = df.dropna(subset=['trx_count', 'latitude', 'longitude']).copy()
        rows_dropped = initial_rows - len(df_cleaned)
        if rows_dropped > 0:
            st.warning(f"Warning: Dropped {rows_dropped} rows due to missing values in core columns.")

        if len(df_cleaned) < 5: # WardSpatial might need a few points
             st.error("Error: Not enough valid data (minimum ~5 recommended).")
             st.stop()

        # --- Convert to GeoDataFrame and Project ---
        st.write("DEBUG: Converting to GeoDataFrame and projecting coordinates...")
        geometry = [Point(xy) for xy in zip(df_cleaned['longitude'], df_cleaned['latitude'])]
        gdf = gpd.GeoDataFrame(df_cleaned, geometry=geometry, crs="EPSG:4326")
        gdf_projected = gdf.to_crs("EPSG:5070") # NAD83 / Conus Albers
        st.write(f"DEBUG: Data projected to EPSG:5070.")

        # Add projected coordinates as columns for WardSpatial attributes
        gdf_projected['proj_x'] = gdf_projected.geometry.x
        gdf_projected['proj_y'] = gdf_projected.geometry.y


        # --- User Input for WardSpatial Parameters ---
        st.sidebar.header("WardSpatial Segmentation Parameters")
        n_territories = st.sidebar.slider("2. Number of Territories (Clusters):", min_value=2, max_value=min(50, len(gdf_projected)//2), value=min(5, len(gdf_projected)//2), step=1)

        max_k_neighbors = len(gdf_projected) - 1
        if max_k_neighbors < 1:
            st.error("Not enough data points to define neighbors.")
            st.stop()
        k_neighbors = st.sidebar.slider("Number of Neighbors (for connectivity graph):", min_value=1, max_value=min(15, max_k_neighbors), value=min(5,max_k_neighbors), step=1)


        # --- WardSpatial Execution ---
        st.markdown("---")
        if st.button(f"3. Run WardSpatial Segmentation for {n_territories} Territories", type="primary"):
            with st.spinner('Building spatial weights and running WardSpatial... This may take a moment.'):

                # --- Prepare attributes for WardSpatial ---
                # We will use scaled projected coordinates and scaled trx_count
                attrs_for_ward = ['proj_x', 'proj_y', 'trx_count']
                data_for_ward = gdf_projected[attrs_for_ward].copy()

                # Scale these attributes
                scaler = StandardScaler()
                data_for_ward_scaled = scaler.fit_transform(data_for_ward)

                # Create a new DataFrame with scaled attributes for WardSpatial
                # WardSpatial expects attributes directly in the GeoDataFrame or as a separate array/df
                # For simplicity, let's add scaled columns to gdf_projected temporarily
                gdf_projected_scaled_attrs = gdf_projected.copy()
                gdf_projected_scaled_attrs['scaled_proj_x'] = data_for_ward_scaled[:, 0]
                gdf_projected_scaled_attrs['scaled_proj_y'] = data_for_ward_scaled[:, 1]
                gdf_projected_scaled_attrs['scaled_trx_count'] = data_for_ward_scaled[:, 2]

                attrs_name_scaled = ['scaled_proj_x', 'scaled_proj_y', 'scaled_trx_count']
                st.write(f"DEBUG: Attributes for WardSpatial (scaled): {attrs_name_scaled}")

                # Create KNN spatial weights matrix from projected coordinates
                st.write(f"DEBUG: Building KNN weights matrix with k={k_neighbors}...")
                try:
                    gdf_projected = gdf_projected.set_geometry('geometry') # Ensure active geometry
                    knn_weights = libpysal.weights.KNN.from_dataframe(gdf_projected, k=k_neighbors)
                    st.write("DEBUG: KNN weights matrix built.")
                except Exception as e_weights:
                    st.error(f"Error building spatial weights: {e_weights}")
                    st.stop()

                # --- Run WardSpatial ---
                st.write("DEBUG: Running WardSpatial algorithm...")
                model_ward = WardSpatial(
                    gdf_projected_scaled_attrs, # Use GDF with scaled attributes
                    w=knn_weights,
                    attrs_name=attrs_name_scaled, # Use names of scaled attribute columns
                    n_clusters=n_territories
                )
                model_ward.solve()
                st.write("DEBUG: WardSpatial solved.")

                # Assign cluster labels back to the original GeoDataFrame (gdf)
                gdf.loc[gdf_projected_scaled_attrs.index, 'cluster'] = model_ward.labels_

            st.success(f"WardSpatial Segmentation Complete! {n_territories} territories generated.")
            st.markdown("---")

            # --- Display Results ---
            st.write("### 4. Segmentation Results")

            # --- Map Visualization ---
            st.write("#### Interactive Map of Territories")
            st.markdown("HCP locations colored by assigned territory. Hover for details.")
            try:
                gdf['cluster'] = gdf['cluster'].astype(str)
                hover_data_dict = {"latitude": False, "longitude": False, "cluster": True, "trx_count": True}
                for col in present_optional_geo:
                    if col in gdf.columns: hover_data_dict[col] = True

                fig = px.scatter_mapbox(gdf.dropna(subset=['cluster']),
                                        lat="latitude",
                                        lon="longitude",
                                        color="cluster",
                                        size="trx_count",
                                        hover_name="hcp_id",
                                        hover_data=hover_data_dict,
                                        color_discrete_sequence=px.colors.qualitative.Safe, # Different color scheme
                                        zoom=3.5,
                                        height=600,
                                        mapbox_style="carto-positron")
                fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
                st.plotly_chart(fig, use_container_width=True)
            except Exception as map_error:
                st.error(f"Error creating map: {map_error}")

            st.markdown("---")

            # --- Geographic Cluster Summary ---
            if present_optional_geo:
                st.write("#### Geographic Territory Summary")
                st.markdown(f"Count of HCPs per Territory and {', '.join(present_optional_geo)}.")
                grouping_fields = ['cluster'] + [col for col in present_optional_geo if col in gdf.columns]
                if len(grouping_fields) > 1 and 'cluster' in gdf.columns:
                    geo_summary = gdf.dropna(subset=['cluster']).groupby(grouping_fields).size().reset_index(name='HCP Count')
                    st.dataframe(geo_summary.sort_values(by=['cluster'] + [col for col in present_optional_geo if col in gdf.columns]))
                else:
                    st.write("Optional geographic columns or cluster assignments not found for summary.")
                st.markdown("*(Use this table to check if territories are geographically consistent)*")
                st.markdown("---")

            # --- Results Table ---
            st.write("#### Full Segmented Data Table")
            display_columns = ['hcp_id', 'trx_count', 'latitude', 'longitude'] + \
                              [col for col in present_optional_geo if col in gdf.columns] + \
                              ['cluster']
            final_display_columns = [col for col in display_columns if col in gdf.columns]
            if 'cluster' in gdf.columns:
                st.dataframe(gdf[final_display_columns].sort_values('cluster'))
            else:
                st.write("Cluster information not available for the table.")


            # --- Download Button ---
            st.markdown("---")
            st.write("### 5. Export Results")
            try:
                output = io.BytesIO()
                if 'cluster' in gdf.columns:
                    df_to_save = gdf[final_display_columns]
                    df_to_save.to_csv(output, index=False, encoding='utf-8')
                    output.seek(0)
                    st.download_button(label="Download Segmented Data as CSV",
                                   data=output,
                                   file_name=f'hcp_wardspatial_territories_{n_territories}.csv',
                                   mime='text/csv',
                                   key='download-ward-csv')
                else:
                    st.write("No segmented data to download.")
            except Exception as download_error:
                st.error(f"Error preparing download link: {download_error}")

    except pd.errors.EmptyDataError:
        st.error("Error: The uploaded CSV file appears to be empty.")
    except ImportError as e_import:
        st.error(f"ImportError: A required library (likely PySAL, spopt, or a dependency) is not installed. Details: {e_import}")
        st.error("Please ensure your environment has all libraries from requirements.txt installed, especially GeoPandas and PySAL components.")
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        st.error("Please ensure the uploaded file is valid and all dependencies are installed.")
        # import traceback # Uncomment for detailed traceback
        # st.code(traceback.format_exc())

else:
    st.info("Awaiting CSV file upload to begin.")