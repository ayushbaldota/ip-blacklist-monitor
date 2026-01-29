/**
 * IP Blacklist Monitor - Google Sheets Integration
 *
 * This script allows you to bulk import IP addresses from a Google Sheet
 * into the IP Blacklist Monitor system.
 *
 * SETUP:
 * 1. Open your Google Sheet
 * 2. Go to Extensions > Apps Script
 * 3. Paste this entire script
 * 4. Update the API_KEY and API_URL constants below
 * 5. Save the script (Ctrl+S)
 * 6. Go back to your sheet and refresh the page
 * 7. You'll see a new menu "IP Blacklist Monitor"
 *
 * USAGE:
 * - Put IP addresses in column A (one per row, starting from row 2)
 * - Optionally add names in column B and descriptions in column C
 * - Click "IP Blacklist Monitor" > "Import IPs to Monitor"
 */

// ============================================================================
// CONFIGURATION - Update these values
// ============================================================================
const API_KEY = 'blk_cf000f60d2a69b1507548b81fa7bb85cb256b0b6f84f0a15';
const API_URL = 'https://blacklistapi.atoztester.com/api/v1';

// ============================================================================
// MENU SETUP
// ============================================================================

/**
 * Creates the custom menu when the spreadsheet opens
 */
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('IP Blacklist Monitor')
    .addItem('Import IPs to Monitor', 'importIPsToMonitor')
    .addItem('Check Status of IPs', 'checkIPStatus')
    .addSeparator()
    .addItem('Clear Results Column', 'clearResults')
    .addToUi();
}

// ============================================================================
// MAIN FUNCTIONS
// ============================================================================

/**
 * Import all IPs from column A to the blacklist monitor
 * Column A: IP Address (required)
 * Column B: Name (optional)
 * Column C: Description (optional)
 * Column D: Tags - comma separated (optional)
 * Column E: Result (will be filled by script)
 */
function importIPsToMonitor() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    SpreadsheetApp.getUi().alert('No data found. Please add IP addresses starting from row 2.');
    return;
  }

  // Get data from columns A-D (IP, Name, Description, Tags)
  const dataRange = sheet.getRange(2, 1, lastRow - 1, 4);
  const data = dataRange.getValues();

  // Filter out empty rows and prepare IPs for import
  const ipsToImport = [];
  const rowIndices = [];

  for (let i = 0; i < data.length; i++) {
    const ip = String(data[i][0]).trim();
    if (ip && isValidIP(ip)) {
      const ipData = {
        ip_address: ip
      };

      // Add optional name
      const name = String(data[i][1]).trim();
      if (name) {
        ipData.name = name;
      }

      // Add optional description
      const description = String(data[i][2]).trim();
      if (description) {
        ipData.description = description;
      }

      // Add optional tags (comma-separated)
      const tagsStr = String(data[i][3]).trim();
      if (tagsStr) {
        ipData.tags = tagsStr.split(',').map(t => t.trim().toLowerCase()).filter(t => t);
      }

      ipsToImport.push(ipData);
      rowIndices.push(i + 2); // +2 because data starts at row 2
    }
  }

  if (ipsToImport.length === 0) {
    SpreadsheetApp.getUi().alert('No valid IP addresses found in column A.');
    return;
  }

  // Confirm with user
  const ui = SpreadsheetApp.getUi();
  const response = ui.alert(
    'Confirm Import',
    `Found ${ipsToImport.length} valid IP address(es). Do you want to import them?`,
    ui.ButtonSet.YES_NO
  );

  if (response !== ui.Button.YES) {
    return;
  }

  // Import in batches of 100 (API limit)
  const batchSize = 100;
  const results = [];

  for (let i = 0; i < ipsToImport.length; i += batchSize) {
    const batch = ipsToImport.slice(i, i + batchSize);
    const batchResult = importBatch(batch);
    results.push(...batchResult);
  }

  // Write results to column E
  for (let i = 0; i < results.length; i++) {
    const rowIndex = rowIndices[i];
    sheet.getRange(rowIndex, 5).setValue(results[i]);
  }

  // Count results
  const added = results.filter(r => r === 'Added').length;
  const skipped = results.filter(r => r.startsWith('Skipped')).length;
  const errors = results.filter(r => r.startsWith('Error')).length;

  ui.alert(
    'Import Complete',
    `Results:\n- Added: ${added}\n- Skipped (already exists): ${skipped}\n- Errors: ${errors}\n\nCheck column E for details.`,
    ui.ButtonSet.OK
  );
}

/**
 * Import a batch of IPs using the bulk endpoint
 */
function importBatch(ips) {
  const results = [];

  try {
    const payload = {
      ips: ips
    };

    const options = {
      method: 'post',
      contentType: 'application/json',
      headers: {
        'X-API-Key': API_KEY
      },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    };

    const response = UrlFetchApp.fetch(`${API_URL}/ips/bulk`, options);
    const responseCode = response.getResponseCode();
    const responseBody = JSON.parse(response.getContentText());

    if (responseCode === 201 || responseCode === 200) {
      // Map results back to IPs
      const apiResults = responseBody.data?.results || responseBody.results || [];

      for (const ip of ips) {
        const result = apiResults.find(r => r.ip_address === ip.ip_address);
        if (result) {
          if (result.status === 'added') {
            results.push('Added');
          } else if (result.status === 'skipped') {
            results.push(`Skipped: ${result.reason || 'already exists'}`);
          } else {
            results.push(`Error: ${result.reason || 'unknown'}`);
          }
        } else {
          results.push('Added');
        }
      }
    } else {
      // API error - mark all as error
      const errorMsg = responseBody.detail || responseBody.error || `HTTP ${responseCode}`;
      for (const ip of ips) {
        results.push(`Error: ${errorMsg}`);
      }
    }
  } catch (error) {
    // Network/script error - mark all as error
    for (const ip of ips) {
      results.push(`Error: ${error.message}`);
    }
  }

  return results;
}

/**
 * Check the blacklist status of IPs in column A
 */
function checkIPStatus() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    SpreadsheetApp.getUi().alert('No data found.');
    return;
  }

  const ipRange = sheet.getRange(2, 1, lastRow - 1, 1);
  const ips = ipRange.getValues();

  const ui = SpreadsheetApp.getUi();
  ui.alert('Checking Status', 'Fetching status for IPs. This may take a moment...', ui.ButtonSet.OK);

  for (let i = 0; i < ips.length; i++) {
    const ip = String(ips[i][0]).trim();
    if (ip && isValidIP(ip)) {
      const status = getIPStatus(ip);
      sheet.getRange(i + 2, 5).setValue(status);
    }
  }

  ui.alert('Status Check Complete', 'Check column E for status results.', ui.ButtonSet.OK);
}

/**
 * Get status of a single IP from the API
 */
function getIPStatus(ip) {
  try {
    const options = {
      method: 'get',
      headers: {
        'X-API-Key': API_KEY
      },
      muteHttpExceptions: true
    };

    const response = UrlFetchApp.fetch(`${API_URL}/ips/${encodeURIComponent(ip)}`, options);
    const responseCode = response.getResponseCode();

    if (responseCode === 200) {
      const data = JSON.parse(response.getContentText());
      const ipData = data.data || data;
      const status = ipData.status || 'unknown';
      const blacklistCount = ipData.blacklist_count || 0;

      if (status === 'blacklisted') {
        return `BLACKLISTED (${blacklistCount} lists)`;
      } else if (status === 'clean') {
        return 'Clean';
      } else if (status === 'pending') {
        return 'Pending check';
      }
      return status;
    } else if (responseCode === 404) {
      return 'Not monitored';
    } else {
      return `Error: HTTP ${responseCode}`;
    }
  } catch (error) {
    return `Error: ${error.message}`;
  }
}

/**
 * Clear the results column (E)
 */
function clearResults() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const lastRow = sheet.getLastRow();

  if (lastRow >= 2) {
    sheet.getRange(2, 5, lastRow - 1, 1).clearContent();
  }

  SpreadsheetApp.getUi().alert('Results column cleared.');
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Validate IP address format (IPv4 and IPv6)
 */
function isValidIP(ip) {
  // IPv4 pattern
  const ipv4Pattern = /^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;

  // Simple IPv6 pattern (covers most common formats)
  const ipv6Pattern = /^(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$|^::(?:[0-9a-fA-F]{1,4}:){0,6}[0-9a-fA-F]{1,4}$|^(?:[0-9a-fA-F]{1,4}:){1,7}:$|^(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}$/;

  return ipv4Pattern.test(ip) || ipv6Pattern.test(ip);
}
