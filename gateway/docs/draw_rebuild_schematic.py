#!/usr/bin/env python3
"""
Render AVC-LAN PHY schematic for gateway rebuild documentation.
Requires: schemdraw (pip install schemdraw)
"""
import os
import schemdraw
import schemdraw.elements as elm

def draw_phy(filename):
    with schemdraw.Drawing(file=filename, show=False, transparent=False, bgcolor='white') as d:
        d.config(fontsize=13, font='sans-serif', inches_per_unit=0.5, unit=3)
        
        # ==========================================
        # Titles
        # ==========================================
        d.add(elm.Label().label("AVC-LAN PHY — new gateway board (RP2040-Zero GP0/GP1)", loc='center').at((8.5, 14.8)).scale(1.35))
        d.add(elm.Label().label("wire the bus pair BY FUNCTION — original schematic H1 silk labels are swapped!", color='red', loc='center').at((8.5, 14.0)).scale(1.05))
        
        # ==========================================
        # RX SECTION
        # ==========================================
        d.add(elm.Label().label("RX", loc='center').at((-1.0, 10.5)).scale(1.3))
        
        # LM339 Opamp / Comparator (unflipped: in1 is -, in2 is +)
        comp = d.add(elm.Opamp().at((9.5, 10.5)).scale(1.2))
        
        y_in1 = comp.absanchors['in1'][1]
        y_in2 = comp.absanchors['in2'][1]
        
        # AVC-LAN connector H1 box
        h1_w = 1.6
        h1_h = (y_in1 - y_in2) + 1.2
        d.add(elm.Rect(corner1=(0, 0), corner2=(h1_w, h1_h)).at((1.0, y_in2 - 0.6)).fill(False).color('black').linewidth(2))
        d.add(elm.Label().label("AVC-LAN (H1)", loc='top').at((1.0 + h1_w/2, y_in1 + 0.7)).scale(1.0))
        
        # Pin circles
        dot_dp = (2.2, y_in1)
        dot_dm = (2.2, y_in2)
        d.add(elm.Dot(open=True).at(dot_dp).scale(1.6).color('black'))
        d.add(elm.Dot(open=True).at(dot_dm).scale(1.6).color('black'))
        d.add(elm.Label().label("Data+", loc='left').at((0.7, y_in1)).scale(1.05))
        d.add(elm.Label().label("Data−", loc='left').at((0.7, y_in2)).scale(1.05))
        
        # Data+ -> R1 100k -> LM339 in1 (-) perfectly straight horizontal
        d.add(elm.Line().at(dot_dp).to((3.6, y_in1)))
        d.add(elm.Resistor().at((3.6, y_in1)).to((6.8, y_in1)).label("R1 100k", loc='top'))
        d.add(elm.Line().at((6.8, y_in1)).to(comp.in1))
        
        # Data- -> R2 100k -> LM339 in2 (+) perfectly straight horizontal
        d.add(elm.Line().at(dot_dm).to((3.6, y_in2)))
        d.add(elm.Resistor().at((3.6, y_in2)).to((6.8, y_in2)).label("R2 100k", loc='bottom'))
        d.add(elm.Line().at((6.8, y_in2)).to(comp.in2))
        
        # LM339 Output
        d.add(elm.Line().at(comp.out).right().length(2.0))
        rx_out_dot = d.here
        d.add(elm.Dot().at(rx_out_dot))
        
        # R3 pull-up to 3V3
        d.add(elm.Resistor().up().at(rx_out_dot).length(2.4).label("R3 4.7k", loc='right', ofst=(0.1, -0.2)))
        d.add(elm.Vdd().label("3V3", loc='top'))
        
        # Line to GP0
        d.add(elm.Line().at(rx_out_dot).right().length(3.0).label("GP0  idle=HIGH, dominant=LOW", loc='right'))
        
        # Text under comparator
        d.add(elm.Label().label("U2 LM339 ¼ (VCC = 5V rail, shared with RP2040)", loc='center').at((8.5, 8.0)).scale(1.05))
        
        # ==========================================
        # TX SECTION
        # ==========================================
        d.add(elm.Label().label("TX", loc='center').at((-1.0, 2.5)).scale(1.3))
        
        # GP1 input
        gp1_start = (0.5, -0.2)
        d.add(elm.Line().at(gp1_start).right().length(1.2).label("GP1", loc='left'))
        d.add(elm.Label().label("HIGH=dominant", loc='bottom').at((0.5, -0.7)).scale(0.85))
        d.add(elm.Resistor().at((1.7, -0.2)).to((3.9, -0.2)).label("R4 2.2k", loc='top'))
        
        # Q1 (BC547 NPN)
        q1 = d.add(elm.BjtNpn().right().anchor('base').at((3.9, -0.2)).label("Q1\nBC547", loc='bottom', ofst=(0.2, -0.7)))
        d.add(elm.Ground().at(q1.emitter))
        
        # Q1 Collector node
        q1_c = q1.collector
        d.add(elm.Line().at(q1_c).to((q1_c[0], 1.0)))
        c_node = (q1_c[0], 1.0)
        d.add(elm.Dot().at(c_node))
        
        # --- Data- branch: Q1 collector <- D2 (BAT54) <- R8 (68Ω) <- Data- ---
        # Diode points LEFT toward Q1 collector (Cathode at Q1 collector, Anode at R8)
        d2_anode = (c_node[0] + 3.0, 1.0)
        d.add(elm.Diode().left().at(d2_anode).to(c_node).label("D2 BAT54", loc='bottom'))
        d.add(elm.Dot().at(c_node))
        d.add(elm.Resistor().at(d2_anode).to((d2_anode[0] + 2.4, 1.0)).label("R8 68Ω", loc='bottom'))
        d.add(elm.Line().at((d2_anode[0] + 2.4, 1.0)).right().length(1.2).label("Data−", loc='right'))
        
        # --- Q1 collector up to Q2 base via R5 ---
        b2_node = (c_node[0], 3.6)
        d.add(elm.Resistor().at(c_node).to(b2_node).label("R5 2.2k", loc='left'))
        d.add(elm.Dot().at(b2_node))
        
        # R6 pull-up from Q2 base to 5V
        r6_top = (b2_node[0], 6.0)
        d.add(elm.Resistor().at(b2_node).to(r6_top).label("R6 1k", loc='left'))
        d.add(elm.Vdd().at(r6_top).label("5V"))
        
        # Q2 (BC327 PNP)
        q2_base_pos = (b2_node[0] + 1.8, b2_node[1])
        d.add(elm.Line().at(b2_node).to(q2_base_pos))
        q2 = d.add(elm.BjtPnp().right().anchor('base').at(q2_base_pos).label("Q2 BC327", loc='right', ofst=(0.4, 0.4)))
        
        # Q2 emitter to 5V rail
        d.add(elm.Vdd().at(q2.emitter).label("5V"))
        
        # Q2 collector down and right to Data+
        y_datap = 2.3
        d.add(elm.Line().at(q2.collector).toy(y_datap))
        q2_c_corner = (q2.collector[0], y_datap)
        
        # Diode D1 (BAT54) points RIGHT (sources current to Data+)
        d1_end = (q2_c_corner[0] + 2.6, y_datap)
        d.add(elm.Diode().right().at(q2_c_corner).to(d1_end).label("D1 BAT54", loc='bottom'))
        d.add(elm.Resistor().at(d1_end).to((d1_end[0] + 2.4, y_datap)).label("R7 68Ω", loc='bottom'))
        d.add(elm.Line().at((d1_end[0] + 2.4, y_datap)).right().length(1.2).label("Data+", loc='right'))
        
        # ==========================================
        # Bottom Summary Notes
        # ==========================================
        d.add(elm.Label().label("GP1 HIGH: Q1 sinks Data− (via D2+R8), Q2 sources Data+ (via D1+R7) • GP1 LOW: both off, diodes block → high-Z recessive", loc='center').at((8.5, -2.8)).scale(0.95))
        d.add(elm.Label().label("5V rail = shared with RP2040 5V (USB powered on bench) • LM339 out is open-collector → pulled to 3V3 only • add 100nF at LM339 VCC", loc='center').at((8.5, -3.6)).scale(0.95))
        d.add(elm.Label().label("Hardware update: BAT54 fast Schottky diodes (trr < 5ns). D2 flipped: Cathode to Q1 collector, Anode to R8.", loc='center').at((8.5, -4.4)).scale(0.95))
        d.add(elm.Label().label("Base drive tuning: R4=2.2k (hard Q1 sat), R5=2.2k + R6=1k (fast Q2 turn-off), R7/R8=68Ω (Vdiff ≈ 0.8–1.0V).", loc='center').at((8.5, -5.2)).scale(0.95))

if __name__ == "__main__":
    docs_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(docs_dir, "avclan-phy-rebuild.png")
    draw_phy(out_path)
    print("Rendered:", out_path)
