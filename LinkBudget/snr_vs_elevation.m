% References
% Calculation of free-space attenuation -  ITU-R P.525-5 - https://www.itu.int/dms_pubrec/itu-r/rec/p/R-REC-P.525-5-202411-I!!PDF-E.pdf

clear all; clc;

fprintf('=================================================================\n');
fprintf('  SNR vs Elevation — Meteor M2-3/M2-4 → B-Raspi Ground Station\n');
fprintf('=================================================================\n\n');

% -------------------------------------------------------------------------
%  1. Get Parameters
% -------------------------------------------------------------------------
run('groundstation_params.m')  %Pull Parameters for groundstation


% -------------------------------------------------------------------------
%  2. ORBITAL / GEOMETRY PARAMETERS
% -------------------------------------------------------------------------

% Slant range as function of elevation angle
% Elevation from 2 to 90 dgr in 1 degree steps
el_deg_vec = 2:1:90;   % Elevation angles to evaluate

% Slant range formula: d = -R*sin(el) + sqrt((R+h)^2 - R^2*cos^2(el))
R_km   = R_earth_km;
h_km   = alt_km;
el_rad = deg2rad(el_deg_vec);
d_km   = -R_km .* sin(el_rad) + sqrt((R_km + h_km)^2 - R_km^2 .* cos(el_rad).^2);
d_m    = d_km * 1e3;

% Plotting slant
figure(1);
plot(el_deg_vec, d_km, 'b-', 'LineWidth', 2);
xlabel('Elevation Angle (degrees)');
ylabel('Slant Range (km)');
title('Slant Range vs Elevation Angle — Meteor M2-3/M2-4');
grid on;
xlim([2 90]);
ylim([0 3500]);

% Add reference markers at key elevations
hold on;
plot(5,  d_km(4),  'ro', 'MarkerSize', 8, 'DisplayName', '5 deg \n');
plot(30, d_km(29), 'gs', 'MarkerSize', 8, 'DisplayName', '30 deg \n');
plot(90, d_km(89), 'k^', 'MarkerSize', 8, 'DisplayName', '90 deg \n');
legend('Slant Range', '5 deg', '30 deg', '90 deg', 'Location', 'NorthEast');
hold off;
fprintf('Slant Range at 5 deg evelvation =  %d km \n', d_km(4));
fprintf('Slant Range at 30 deg evelvation =  %d km \n', d_km(29));;
fprintf('Slant Range at 90 deg evelvation =  %d km \n', d_km(89));

% -------------------------------------------------------------------------
%  3. FREE-SPACE PATH LOSS (FSPL)
% -------------------------------------------------------------------------
% FSPL(dB) = 20*log10(d) + 20*log10(f) + 20*log10(4*pi/c)
FSPL_dB = 20*log10(d_m) + 20*log10(f_Hz) + 20*log10(4*pi/c);

% Plotting FSPL
figure(2);
plot(el_deg_vec, FSPL_dB, 'r-', 'LineWidth', 2);
xlabel('Elevation Angle (degrees)');
ylabel('Free-Space Path Loss (dB)');
title('FSPL vs Elevation Angle — Meteor M2-3/M2-4');
grid on;
xlim([2 90]);

% Add reference markers
hold on;
plot(5,  FSPL_dB(4),  'ro', 'MarkerSize', 8);
plot(30, FSPL_dB(29), 'gs', 'MarkerSize', 8);
plot(90, FSPL_dB(89), 'k^', 'MarkerSize', 8);
legend('FSPL', '5 deg', '30 deg', '90 deg', 'Location', 'NorthEast');
hold off;

fprintf('FSPL 5 deg evelvation = %d dB \n', FSPL_dB(4));
fprintf('FSPL 30 deg evelvation = %d dB \n', FSPL_dB(29));
fprintf('FSPL 90 deg evelvation = %d dB \n', FSPL_dB(89));


% -------------------------------------------------------------------------
%  4. Recieved Power and SNR Calculation
% -------------------------------------------------------------------------

% Received Power = EIRP - FSPL - L_total + G_rx - L_coax
% C/N0 = Pr - k_B - T_sys
% SNR = C/N0 - 10*log10(BW)

% Received power at each elevation angle
Pr_dBW = EIRP_dBW - FSPL_dB - L_total_dB + G_rx_dBi - L_coax_dB;

% Carrier to noise density
CN0_dBHz = Pr_dBW - k_B_dB - T_sys_dBK;

% Link margin above decoding threshold
margin_dB = CN0_dBHz - C_N0_req_dBHz;

fprintf('Received Power at 5 deg  = %.2f dBW\n', Pr_dBW(4));
fprintf('Received Power at 30 deg = %.2f dBW\n', Pr_dBW(29));
fprintf('Received Power at 90 deg = %.2f dBW\n', Pr_dBW(89));
fprintf('C/N0 at 5 deg            = %.2f dBHz\n', CN0_dBHz(4));
fprintf('C/N0 at 30 deg           = %.2f dBHz\n', CN0_dBHz(29));
fprintf('C/N0 at 90 deg           = %.2f dBHz\n', CN0_dBHz(89));
fprintf('Link margin at 5 deg     = %.2f dB\n',   margin_dB(4));
fprintf('Link margin at 90 deg    = %.2f dB\n',   margin_dB(89));
fprintf('Required C/N0            = %.2f dBHz\n', C_N0_req_dBHz);

figure(3);
plot(el_deg_vec, margin_dB, 'b-', 'LineWidth', 2);
hold on;
yline(3,  'g--', 'LineWidth', 1.5, 'Label', 'Good (3 dB)');
yline(0,  'r--', 'LineWidth', 1.5, 'Label', 'Decode threshold');
xlabel('Elevation Angle (degrees)');
ylabel('Link Margin (dB)');
title('Link Margin vs Elevation — Meteor M2-3/M2-4, Turnstile');
grid on;
xlim([2 90]);
hold off;
