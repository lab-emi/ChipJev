v {xschem version=3.4.5 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {sky130-ampN-gbw chipjev seed 0: cs_n+cs_n} 0 -140 0 0 0.5 0.5 {}
T {ChipJev design on SKY130 (TT), VDD = 1.8 V} 0 -100 0 0 0.3 0.3 {}
C {sky130_fd_pr/nfet_01v8.sym} 0 0 0 0 {name=M1 L=0.252333 W=126.167 nf=3 mult=1 ad=24.3922 as=24.3922 pd=169.382 ps=169.382 nrd=0.00229855 nrs=0.00229855 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 20 -30 0 0 {name=l1 sig_type=std_logic lab=o1}
C {devices/lab_pin.sym} -20 0 0 0 {name=l2 sig_type=std_logic lab=in}
C {devices/lab_pin.sym} 20 30 0 0 {name=l3 sig_type=std_logic lab=0}
C {devices/lab_pin.sym} 20 0 0 0 {name=l4 sig_type=std_logic lab=0}
C {sky130_fd_pr/pfet_01v8.sym} 240 0 0 0 {name=M2 L=0.252333 W=52.99 nf=2 mult=1 ad=7.68355 as=15.3671 pd=53.57 ps=107.14 nrd=0.00547273 nrs=0.00547273 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 260 30 0 0 {name=l5 sig_type=std_logic lab=o1}
C {devices/lab_pin.sym} 220 0 0 0 {name=l6 sig_type=std_logic lab=s1ld}
C {devices/lab_pin.sym} 260 -30 0 0 {name=l7 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 260 0 0 0 {name=l8 sig_type=std_logic lab=vdd}
C {sky130_fd_pr/nfet_01v8.sym} 480 0 0 0 {name=M3 L=0.15 W=75 nf=2 mult=1 ad=10.875 as=21.75 pd=75.58 ps=151.16 nrd=0.00386667 nrs=0.00386667 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 500 -30 0 0 {name=l9 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} 460 0 0 0 {name=l10 sig_type=std_logic lab=o1}
C {devices/lab_pin.sym} 500 30 0 0 {name=l11 sig_type=std_logic lab=0}
C {devices/lab_pin.sym} 500 0 0 0 {name=l12 sig_type=std_logic lab=0}
C {sky130_fd_pr/pfet_01v8.sym} 720 0 0 0 {name=M4 L=0.15 W=48.6 nf=1 mult=1 ad=14.094 as=14.094 pd=97.78 ps=97.78 nrd=0.00596708 nrs=0.00596708 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 740 30 0 0 {name=l13 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} 700 0 0 0 {name=l14 sig_type=std_logic lab=s2ld}
C {devices/lab_pin.sym} 740 -30 0 0 {name=l15 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 740 0 0 0 {name=l16 sig_type=std_logic lab=vdd}
C {devices/vsource.sym} 960 0 0 0 {name=VDD value=1.8 m=1}
C {devices/lab_pin.sym} 960 -30 0 0 {name=l17 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 960 30 0 0 {name=l18 sig_type=std_logic lab=0}
C {devices/vsource.sym} 1200 0 0 0 {name=V_S1LD value=0.1025 m=1}
C {devices/lab_pin.sym} 1200 -30 0 0 {name=l19 sig_type=std_logic lab=s1ld}
C {devices/lab_pin.sym} 1200 30 0 0 {name=l20 sig_type=std_logic lab=0}
C {devices/vsource.sym} 0 200 0 0 {name=V_S2LD value=0.2775 m=1}
C {devices/lab_pin.sym} 0 170 0 0 {name=l21 sig_type=std_logic lab=s2ld}
C {devices/lab_pin.sym} 0 230 0 0 {name=l22 sig_type=std_logic lab=0}
