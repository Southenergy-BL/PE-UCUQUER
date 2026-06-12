import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
import os

# ==========================================
# 1. CONFIGURACIÓN Y CONSTANTES
# ==========================================
st.set_page_config(page_title="Monitoreo de Activos Eólicos", layout="wide")

# Colores específicos para cada central en lugar de por tecnología
COLORES_CENTRALES = {
    'PMGD PE UCUQUER': '#8ECAE6',  # Celeste
    'PE UCUQUER II': '#023047'     # Azul oscuro
}

# ⚠️ IMPORTANTE: Actualizar con la potencia real instalada de cada parque
POTENCIA_INSTALADA = {
    'PMGD PE UCUQUER': 7.2,  # MW (Ejemplo PMGD)
    'PE UCUQUER II': 10.75    # MW (Ejemplo)
}

CONFIG_PLOTLY = {'separators': ',.', 'displayModeBar': False}

def formato_cl(valor):
    """Aplica formato numérico estándar chileno (1.234,56)"""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def tooltip_cl(unidad):
    return '%{y:,.2f} ' + unidad + '<extra></extra>'.replace(",", "X").replace(".", ",").replace("X", ".")

# ==========================================
# 2. MOTOR DE DATOS
# ==========================================
@st.cache_data
def cargar_y_procesar_datos(ruta_archivo):
    try:
        df = pd.read_excel(ruta_archivo)
    except:
        df = pd.read_csv(ruta_archivo)
        
    df.columns = df.columns.str.strip()
    df = df.rename(columns={
        'Fecha y Hora': 'Fecha_Hora',
        'Nombre Central': 'Central',
        'Generación Real (MWh)': 'Generacion_MW'
    })
    
    # Filtrar EXCLUSIVAMENTE por las centrales de interés
    centrales_objetivo = ['PMGD PE UCUQUER', 'PE UCUQUER II']
    df = df[df['Central'].isin(centrales_objetivo)].copy()
    
    df['Fecha_Hora'] = pd.to_datetime(df['Fecha_Hora'])
    df['Fecha'] = df['Fecha_Hora'].dt.normalize()
    df['Hora'] = df['Fecha_Hora'].dt.hour + 1
    
    df['Generacion_MW'] = pd.to_numeric(df['Generacion_MW'], errors='coerce').fillna(0)
    
    return df

@st.cache_data
def cargar_cmg(ruta_cmg):
    if str(ruta_cmg).lower().endswith('.xlsx'):
        df_cmg = pd.read_excel(ruta_cmg)
    else:
        df_cmg = pd.read_csv(ruta_cmg, encoding='latin1')
    
    cols_nodos = [col for col in df_cmg.columns if 'CMg' in col]
    col_cmg = cols_nodos[0]
    df_cmg = df_cmg.rename(columns={col_cmg: 'CMg_USD'})
    
    def limpiar_nombre_nodo(nombre):
        nombre = nombre.replace('CMg[USD/MWh]_', '')
        return re.sub(r'_+', ' ', nombre).strip()
        
    df_cmg['Nodo'] = limpiar_nombre_nodo(col_cmg)
    df_cmg['CMg_USD'] = pd.to_numeric(df_cmg['CMg_USD'], errors='coerce').fillna(0)
    
    df_cmg['FECHA'] = pd.to_datetime(df_cmg['FECHA'])
    df_cmg['Fecha_Hora'] = df_cmg['FECHA'] + pd.to_timedelta(df_cmg['HRA'] - 1, unit='h')
    
    return df_cmg

def calcular_rampas(df_agrupado):
    df = df_agrupado.sort_values(by=['Central', 'Hora']).copy()
    df['Delta_MW_hr'] = df.groupby('Central', observed=False)['Generacion_MW'].diff().fillna(0)
    df['Rampa_MW_min'] = df['Delta_MW_hr'] / 60
    return df

# ==========================================
# 3. INTERFAZ Y PESTAÑAS
# ==========================================
st.title("🌬️ Monitoreo de Activos: Complejo Ucuquer")

RUTA_GEN = os.path.join("datos", "Generación 2025-May 2026.xlsx")
RUTA_CMG = os.path.join("datos", "CMg_Multibarra_Con_Promedios.xlsx")

try:
    df_completo = cargar_y_procesar_datos(RUTA_GEN)
    hay_datos_cmg = True
    try:
        df_precios = cargar_cmg(RUTA_CMG)
        # Cruzar datos de generación con CMg para calcular valorización
        df_completo = pd.merge(df_completo, df_precios[['Fecha_Hora', 'CMg_USD']], on='Fecha_Hora', how='left')
        df_completo['Ingreso_Est_USD'] = df_completo['Generacion_MW'] * df_completo['CMg_USD']
    except Exception as e:
        hay_datos_cmg = False
        st.error(f"Error cargando CMg: {e}")
    
    tab_op, tab_econ, tab_kpi, tab_heat = st.tabs([
        "📊 Operación Diaria", 
        "💰 Valorización y CMg", 
        "📈 KPIs y Factor de Capacidad", 
        "📅 Mapa de Calor"
    ])
    
    # ---------------------------------------------------------
    # PESTAÑA 1: OPERACIÓN Y RAMPAS POR PARQUE
    # ---------------------------------------------------------
    with tab_op:
        fechas_disp = df_completo['Fecha'].dt.date.dropna().unique()
        c_ctrl1, c_ctrl2 = st.columns(2)
        with c_ctrl1: vista_despacho = st.radio("Vista:", ["Diaria", "Semanal"], horizontal=True)
        with c_ctrl2: fecha_sel = st.selectbox("Fecha de Análisis:", fechas_disp)
        
        fecha_filtro = pd.to_datetime(fecha_sel)
        df_dia = df_completo[df_completo['Fecha'] == fecha_filtro]
        
        # Calcular rampas (variaciones) por parque
        df_rampas = calcular_rampas(df_dia)
        max_rampa_subida = df_rampas['Rampa_MW_min'].max()
        max_rampa_bajada = df_rampas['Rampa_MW_min'].min()
        
        c1, c2 = st.columns(2)
        c1.metric("Máxima Rampa de Subida (Día)", f"+{formato_cl(max_rampa_subida)} MW/min")
        c2.metric("Máxima Rampa de Caída (Día)", f"{formato_cl(max_rampa_bajada)} MW/min")
        
        st.divider()
        col_ch1, col_ch2 = st.columns([3, 2])
        
        with col_ch1:
            if vista_despacho == "Diaria":
                fig_area = px.area(df_dia, x="Hora", y="Generacion_MW", color="Central", color_discrete_map=COLORES_CENTRALES)
                fig_area.update_layout(xaxis=dict(tickmode='linear', dtick=1))
            else:
                ini_sem = fecha_filtro - pd.Timedelta(days=fecha_filtro.weekday())
                fin_sem = ini_sem + pd.Timedelta(days=6)
                df_sem = df_completo[(df_completo['Fecha'] >= ini_sem) & (df_completo['Fecha'] <= fin_sem)]
                fig_area = px.area(df_sem, x="Fecha_Hora", y="Generacion_MW", color="Central", color_discrete_map=COLORES_CENTRALES)
                fig_area.update_layout(xaxis=dict(range=[ini_sem, fin_sem + pd.Timedelta(hours=23, minutes=59)]))
            
            fig_area.update_layout(hovermode="x unified", yaxis_title="Generación (MWh)", title="Curva de Inyección por Parque")
            st.plotly_chart(fig_area, use_container_width=True, config=CONFIG_PLOTLY)

        with col_ch2:
            fig_bar = px.bar(df_rampas, x='Hora', y='Rampa_MW_min', color='Central', barmode='group', color_discrete_map=COLORES_CENTRALES)
            fig_bar.add_hline(y=0, line_color="black")
            fig_bar.update_layout(yaxis_title="Tasa Cambio (MW/min)", title="Volatilidad Eólica (Rampas Horarias)")
            st.plotly_chart(fig_bar, use_container_width=True, config=CONFIG_PLOTLY)

    # ---------------------------------------------------------
    # PESTAÑA 2: VALORIZACIÓN Y COSTO MARGINAL
    # ---------------------------------------------------------
    with tab_econ:
        if hay_datos_cmg:
            st.markdown("#### Captura de Precios e Ingresos Estimados")
            ingreso_total = df_completo['Ingreso_Est_USD'].sum()
            gen_total = df_completo['Generacion_MW'].sum()
            precio_capturado = ingreso_total / gen_total if gen_total > 0 else 0
            cmg_promedio = df_precios['CMg_USD'].mean()
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Ingreso Teórico Total", f"$ {formato_cl(ingreso_total)} USD")
            c2.metric("Precio Capturado (Promedio Ponderado)", f"{formato_cl(precio_capturado)} USD/MWh")
            c3.metric("CMg Promedio del Nodo", f"{formato_cl(cmg_promedio)} USD/MWh")
            
            st.divider()
            
            df_plot_econ = df_completo.groupby(['Fecha_Hora', 'Central'])[['Generacion_MW', 'CMg_USD']].sum().reset_index()
            
            fig_econ = make_subplots(specs=[[{"secondary_y": True}]])
            for central, color in COLORES_CENTRALES.items():
                df_c = df_plot_econ[df_plot_econ['Central'] == central]
                fig_econ.add_trace(go.Bar(x=df_c['Fecha_Hora'], y=df_c['Generacion_MW'], name=central, marker_color=color), secondary_y=False)
            
            fig_econ.add_trace(go.Scatter(x=df_precios['Fecha_Hora'], y=df_precios['CMg_USD'], name="CMg Nodo", mode='lines', line=dict(color='red', width=2)), secondary_y=True)
            
            fig_econ.update_layout(barmode='stack', hovermode="x unified", title="Inyección vs Costo Marginal")
            fig_econ.update_yaxes(title_text="Generación (MWh)", secondary_y=False)
            fig_econ.update_yaxes(title_text="CMg (USD/MWh)", secondary_y=True, showgrid=False)
            st.plotly_chart(fig_econ, use_container_width=True, config=CONFIG_PLOTLY)
        else:
            st.warning("Datos de Costos Marginales no disponibles.")

    # ---------------------------------------------------------
    # PESTAÑA 3: KPIs Y FACTOR DE CAPACIDAD
    # ---------------------------------------------------------
    with tab_kpi:
        horas_totales = len(df_completo['Fecha'].unique()) * 24
        df_kpi = df_completo.groupby('Central').agg(
            Generacion_Total=('Generacion_MW', 'sum'),
            Max_Generacion=('Generacion_MW', 'max')
        ).reset_index()
        
        df_kpi['Factor_Capacidad_%'] = df_kpi.apply(
            lambda r: (r['Generacion_Total'] / (POTENCIA_INSTALADA.get(r['Central'], 1) * horas_totales)) * 100, axis=1
        )
        
        col_k1, col_k2 = st.columns(2)
        with col_k1:
            fig_fc = px.bar(df_kpi, x='Central', y='Factor_Capacidad_%', color='Central', color_discrete_map=COLORES_CENTRALES, text_auto='.2f')
            fig_fc.update_layout(title="Factor de Capacidad Real vs Nominal")
            st.plotly_chart(fig_fc, use_container_width=True, config=CONFIG_PLOTLY)
            
        with col_k2:
            fig_pie = px.pie(df_kpi, values='Generacion_Total', names='Central', color='Central', color_discrete_map=COLORES_CENTRALES, title="Participación en la Producción Total")
            st.plotly_chart(fig_pie, use_container_width=True, config=CONFIG_PLOTLY)

    # ---------------------------------------------------------
    # PESTAÑA 4: MAPA DE CALOR
    # ---------------------------------------------------------
    with tab_heat:
        st.markdown("#### Perfil Horario de Generación Combinada (Ucuquer I y II)")
        df_heat = df_completo.groupby(['Fecha', 'Hora'])['Generacion_MW'].sum().reset_index()
        
        fig_heat = px.density_heatmap(
            df_heat, x="Hora", y="Fecha", z="Generacion_MW", 
            color_continuous_scale="Viridis",
            nbinsx=24
        )
        fig_heat.update_layout(xaxis=dict(tickmode='linear', dtick=1), yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig_heat, use_container_width=True, config=CONFIG_PLOTLY)

except Exception as e:
    st.error(f"Error procesando la plataforma: {e}")

# ==========================================
# 4. MÓDULO DE EXPORTACIÓN Y REPORTES
# ==========================================
st.sidebar.title("📥 Exportar Resultados")

if 'df_kpi' in locals():
    # Reporte centrado en las dos centrales
    reporte_txt = f"""REPORTE DE OPERACIÓN - COMPLEJO UCUQUER
========================================
Fecha de Evaluación: {fecha_sel}

--- MÉTRICAS GLOBALES DEL PERIODO ---
Generación Total: {formato_cl(df_kpi['Generacion_Total'].sum())} MWh
"""
    if hay_datos_cmg:
        reporte_txt += f"""Ingreso Teórico Estimado: $ {formato_cl(ingreso_total)} USD
Precio Capturado (Ponderado): {formato_cl(precio_capturado)} USD/MWh
"""
    reporte_txt += "\n--- DESGLOSE POR ACTIVO ---\n"
    for _, row in df_kpi.iterrows():
        reporte_txt += f"""{row['Central']}:
  - Producción: {formato_cl(row['Generacion_Total'])} MWh
  - Factor de Capacidad: {formato_cl(row['Factor_Capacidad_%'])} %
  - Máxima Inyección Horaria: {formato_cl(row['Max_Generacion'])} MW\n"""

    st.sidebar.download_button("📄 Descargar Reporte (TXT)", data=reporte_txt, file_name="Reporte_Ucuquer.txt", mime="text/plain")
    st.sidebar.divider()
    
    # Exportar solo la data filtrada de Ucuquer
    csv_data = df_completo.to_csv(index=False, sep=';', decimal=',')
    st.sidebar.download_button("📊 Descargar Datos Consolidados (CSV)", data=csv_data, file_name="Datos_Ucuquer.csv", mime="text/csv")