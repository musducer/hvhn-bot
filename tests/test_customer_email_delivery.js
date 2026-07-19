const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('phanphoi.gs', 'utf8');
const sent = [];
const properties = {
  CUSTOMER_NOTICE_IMAGE_FILE_ID: 'notice-file-id',
};
const state = {
  guideAvailable: true,
  noticeAvailable: true,
  rejectMultipleAttachments: false,
};

function blob(name) {
  return {
    name,
    setName(nextName) {
      this.name = nextName;
      return this;
    },
  };
}

function guideFile() {
  return {
    getAs() {
      return blob('guide-export.pdf');
    },
  };
}

function noticeFile() {
  return {
    getMimeType() {
      return 'image/jpeg';
    },
    getBlob() {
      return blob('notice.jpg');
    },
    getName() {
      return 'notice.jpg';
    },
  };
}

const context = {
  MimeType: { PDF: 'application/pdf' },
  DriveApp: {
    getFileById(id) {
      if (id === '1DeHcLRGqFWfNVETFRdfx-4dro1-yMsEf' && state.guideAvailable) return guideFile();
      if (id === 'notice-file-id' && state.noticeAvailable) return noticeFile();
      throw new Error('Drive file unavailable: ' + id);
    },
  },
  PropertiesService: {
    getScriptProperties() {
      return {
        getProperty(key) {
          return properties[key] || null;
        },
      };
    },
  },
  MailApp: {
    sendEmail(message) {
      const attachments = message.attachments || [];
      if (state.rejectMultipleAttachments && attachments.length > 1) {
        throw new Error('simulated multi-attachment rejection');
      }
      sent.push({
        body: message.body,
        htmlBody: message.htmlBody,
        attachments: Array.from(attachments, item => item.name),
      });
    },
  },
  SpreadsheetApp: undefined,
  console,
};

vm.runInNewContext(source, context, { filename: 'phanphoi.gs' });

function reset() {
  sent.length = 0;
  state.guideAvailable = true;
  state.noticeAvailable = true;
  state.rejectMultipleAttachments = false;
}

reset();
let result = context._pmtSendInviteEmail('student@example.com', 'Nguyen Van A', 'https://discord.gg/example');
assert.strictEqual(result, 'sent_with_guide_and_notice');
assert.strictEqual(sent.length, 1);
assert.deepStrictEqual(sent[0].attachments, ['Huong-dan-su-dung-he-thong-HVHN.pdf', 'notice.jpg']);
assert.ok(sent[0].body.includes('https://docs.google.com/document/d/1DeHcLRGqFWfNVETFRdfx-4dro1-yMsEf/edit?usp=sharing'));
assert.ok(sent[0].htmlBody.includes('Hướng dẫn sử dụng hệ thống HVHN'));
assert.ok(!sent[0].body.includes('PayOS'));

reset();
state.rejectMultipleAttachments = true;
result = context._pmtSendInviteEmail('student@example.com', 'Nguyen Van A', 'https://discord.gg/example');
assert.strictEqual(result, 'sent_with_guide_only');
assert.strictEqual(sent.length, 1);
assert.deepStrictEqual(sent[0].attachments, ['Huong-dan-su-dung-he-thong-HVHN.pdf']);
assert.ok(sent[0].body.includes('bản PDF hướng dẫn'));

reset();
state.guideAvailable = false;
delete properties.CUSTOMER_NOTICE_IMAGE_FILE_ID;
result = context._preorderSendInviteEmail('student@example.com', 'Nguyen Van A', 'https://discord.gg/example');
assert.strictEqual(result, 'sent_with_guide_link_only');
assert.strictEqual(sent.length, 1);
assert.deepStrictEqual(sent[0].attachments, []);
assert.ok(sent[0].body.includes('https://docs.google.com/document/d/1DeHcLRGqFWfNVETFRdfx-4dro1-yMsEf/edit?usp=sharing'));
assert.ok(sent[0].htmlBody.includes('Việc cần làm trước khi sử dụng hệ thống'));

console.log('Apps Script customer-email delivery paths passed.');
